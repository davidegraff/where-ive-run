#!/usr/bin/env python3
"""Download every run from your Strava account (with its GPS route).

Usage:  python3 scripts/fetch_strava_runs.py

First run: asks for your Strava API app's Client ID and Secret, opens your
browser so you can approve access, then saves a token in data/strava_token.json
(chmod 600) so later runs don't need the login again.

Output: data/runs.json and data/runs.js (the latter is loaded by heatmap.html).
"""
import getpass
import http.server
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TOKEN_FILE = os.path.join(DATA, "strava_token.json")
PORT = 8723
REDIRECT = f"http://localhost:{PORT}/callback"
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}


def post(url, params):
    body = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body)) as r:
        return json.load(r)


def save_token(tok):
    os.makedirs(DATA, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tok, f)
    os.chmod(TOKEN_FILE, 0o600)


def browser_login(client_id, client_secret):
    code_box = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q:
                code_box["code"] = q["code"][0]
                code_box["scope"] = q.get("scope", [""])[0]
                msg = "Strava access approved. You can close this tab."
            else:
                code_box["error"] = q.get("error", ["unknown"])[0]
                msg = "Strava access was not approved: " + code_box["error"]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h2 style='font-family:sans-serif'>{msg}</h2>".encode())

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("localhost", PORT), Handler)
    url = "https://www.strava.com/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "activity:read_all",
    })
    print("\nOpening your browser to approve access. If it doesn't open, visit:\n" + url + "\n")
    webbrowser.open(url)
    while not code_box:
        server.handle_request()
    server.server_close()
    if "error" in code_box:
        sys.exit("Login failed: " + code_box["error"])
    if "activity:read" not in code_box["scope"]:
        sys.exit("You need to tick the 'View data about your activities' box. Run the script again.")

    tok = post("https://www.strava.com/oauth/token", {
        "client_id": client_id, "client_secret": client_secret,
        "code": code_box["code"], "grant_type": "authorization_code",
    })
    tok["client_id"], tok["client_secret"] = client_id, client_secret
    tok.pop("athlete", None)
    save_token(tok)
    return tok


def get_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            tok = json.load(f)
        if tok["expires_at"] - 60 > time.time():
            return tok
        new = post("https://www.strava.com/oauth/token", {
            "client_id": tok["client_id"], "client_secret": tok["client_secret"],
            "refresh_token": tok["refresh_token"], "grant_type": "refresh_token",
        })
        tok.update(new)
        save_token(tok)
        return tok

    print("Strava API app setup (one time): https://www.strava.com/settings/api")
    print("  - 'Authorization Callback Domain' must be: localhost\n")
    client_id = input("Client ID: ").strip()
    client_secret = getpass.getpass("Client Secret (hidden as you type): ").strip()
    return browser_login(client_id, client_secret)


def api_get(path, token, params):
    url = "https://www.strava.com/api/v3" + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    while True:
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("  Strava rate limit reached; waiting 15 minutes...")
                time.sleep(15 * 60 + 5)
                continue
            raise


def main():
    tok = get_token()
    runs, page = [], 1
    print("Downloading activities...")
    while True:
        batch = api_get("/athlete/activities", tok["access_token"], {"per_page": 200, "page": page})
        if not batch:
            break
        for a in batch:
            if a.get("sport_type", a.get("type")) not in RUN_TYPES and a.get("type") not in RUN_TYPES:
                continue
            runs.append({
                "id": a["id"],
                "name": a.get("name", ""),
                "date": a.get("start_date_local", ""),
                "type": a.get("sport_type") or a.get("type"),
                "distance_m": a.get("distance", 0),
                "moving_s": a.get("moving_time", 0),
                "elev_m": a.get("total_elevation_gain", 0),
                "start": a.get("start_latlng") or None,
                "polyline": (a.get("map") or {}).get("summary_polyline") or "",
            })
        print(f"  page {page}: {len(batch)} activities, {len(runs)} runs so far")
        page += 1

    runs.sort(key=lambda r: r["date"])
    with open(os.path.join(DATA, "runs.json"), "w") as f:
        json.dump(runs, f)
    with open(os.path.join(DATA, "runs.js"), "w") as f:
        f.write("window.RUNS = " + json.dumps(runs) + ";\n")
    with_gps = sum(1 for r in runs if r["polyline"])
    km = sum(r["distance_m"] for r in runs) / 1000
    print(f"\nDone: {len(runs)} runs ({with_gps} with GPS), {km:,.0f} km total.")
    print("Saved data/runs.json and data/runs.js. Open heatmap.html to see the map.")


if __name__ == "__main__":
    main()
