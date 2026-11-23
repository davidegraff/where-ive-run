#!/usr/bin/env python3
"""Download every run from your Strava account (with its GPS route).

Usage:  uv run python scripts/fetch_strava_runs.py

First run: asks for your Strava API app's Client ID and Secret, opens your
browser so you can approve access, then saves a token in data/strava_token.json
(chmod 600) so later runs don't need the login again.

Output: data/runs.json and data/runs.js (the latter is loaded by heatmap.html).
"""
from __future__ import annotations

import getpass
import http.server
import json
import os
import sys
import time
import urllib.parse
import webbrowser
from typing import Any, TypedDict

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TOKEN_FILE = os.path.join(DATA, "strava_token.json")
PORT = 8723
REDIRECT = f"http://localhost:{PORT}/callback"
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}
TOKEN_URL = "https://www.strava.com/oauth/token"
AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
API_BASE = "https://www.strava.com/api/v3"
TIMEOUT = 60


class Token(TypedDict):
    access_token: str
    refresh_token: str
    expires_at: int
    client_id: str
    client_secret: str


class Run(TypedDict):
    id: int
    name: str
    date: str
    type: str | None
    distance_m: float
    moving_s: int
    elev_m: float
    start: list[float] | None
    polyline: str


def post(url: str, params: dict[str, str]) -> dict[str, Any]:
    r = requests.post(url, data=params, timeout=TIMEOUT)
    r.raise_for_status()
    result: dict[str, Any] = r.json()
    return result


def save_token(tok: Token) -> None:
    os.makedirs(DATA, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tok, f)
    os.chmod(TOKEN_FILE, 0o600)


def browser_login(client_id: str, client_secret: str) -> Token:
    code_box: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
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

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = http.server.HTTPServer(("localhost", PORT), Handler)
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
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

    resp = post(TOKEN_URL, {
        "client_id": client_id, "client_secret": client_secret,
        "code": code_box["code"], "grant_type": "authorization_code",
    })
    tok: Token = {
        "access_token": resp["access_token"],
        "refresh_token": resp["refresh_token"],
        "expires_at": resp["expires_at"],
        "client_id": client_id,
        "client_secret": client_secret,
    }
    save_token(tok)
    return tok


def get_token() -> Token:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            tok: Token = json.load(f)
        if tok["expires_at"] - 60 > time.time():
            return tok
        new = post(TOKEN_URL, {
            "client_id": tok["client_id"], "client_secret": tok["client_secret"],
            "refresh_token": tok["refresh_token"], "grant_type": "refresh_token",
        })
        tok["access_token"] = new["access_token"]
        tok["refresh_token"] = new["refresh_token"]
        tok["expires_at"] = new["expires_at"]
        save_token(tok)
        return tok

    print("Strava API app setup (one time): https://www.strava.com/settings/api")
    print("  - 'Authorization Callback Domain' must be: localhost\n")
    client_id = input("Client ID: ").strip()
    client_secret = getpass.getpass("Client Secret (hidden as you type): ").strip()
    return browser_login(client_id, client_secret)


def api_get(session: requests.Session, path: str, params: dict[str, int]) -> list[dict[str, Any]]:
    while True:
        r = session.get(API_BASE + path, params=params, timeout=TIMEOUT)
        if r.status_code == 429:
            print("  Strava rate limit reached; waiting 15 minutes...")
            time.sleep(15 * 60 + 5)
            continue
        r.raise_for_status()
        result: list[dict[str, Any]] = r.json()
        return result


def main() -> None:
    tok = get_token()
    runs: list[Run] = []
    page = 1
    print("Downloading activities...")
    with requests.Session() as session:
        session.headers["Authorization"] = "Bearer " + tok["access_token"]
        while True:
            batch = api_get(session, "/athlete/activities", {"per_page": 200, "page": page})
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
