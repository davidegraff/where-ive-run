"""Who is making this request?

Every route depends on current_user(), and every row in the database is scoped to the id it returns.
How that id is found is chosen by the AUTH setting (see settings.py), and lives only in this file:

    "browser"  (default) Each browser gets its own private space: a random secret in a cookie, set on
               its first visit. No sign-in, but clearing cookies or switching devices starts over empty,
               and anyone who copies the cookie sees that browser's data.
    "local"    Everyone is the same user, "local". For running it just for yourself.

To add real accounts (OAuth, passwords, a reverse proxy's auth header, ...), add another scheme: a
middleware that puts the user's id in request.state.user (or answers 401 itself), registered in
install(). Nothing outside this file needs to change.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from http.cookies import SimpleCookie

from fastapi import FastAPI, HTTPException, Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SCHEMES = ("browser", "local")

COOKIE = "wir_browser"
COOKIE_MAX_AGE_S = 400 * 24 * 3600
"""The most browsers allow. The cookie is sent again with every response, so it only expires after
400 days without a visit."""
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")  # secrets.token_urlsafe(32)


def current_user(request: Request) -> str:
    user: str | None = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not signed in")
    return user


def install(app: FastAPI, scheme: str) -> None:
    """Add the middleware for the AUTH scheme. It covers the page too, so the cookie is set on first load."""
    if scheme == "browser":
        app.add_middleware(BrowserId)
    elif scheme == "local":
        app.add_middleware(FixedUser, user="local")
    else:
        raise ValueError(f"AUTH must be one of {', '.join(SCHEMES)}, not {scheme!r}")


class FixedUser:
    def __init__(self, app: ASGIApp, user: str) -> None:
        self.app, self.user = app, user

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["user"] = self.user
        await self.app(scope, receive, send)


class BrowserId:
    """A private space per browser, identified by a random secret in an HttpOnly cookie.

    The database stores a hash of the secret, not the secret itself, so a copy of app.db can't be
    used to read anyone's data through the site.

    Plain ASGI rather than BaseHTTPMiddleware, so streamed uploads and import progress pass straight through.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict((k.decode("latin-1"), v.decode("latin-1")) for k, v in scope["headers"])
        token = _read_cookie(headers.get("cookie", ""))
        if token is None:
            token = secrets.token_urlsafe(32)
        scope.setdefault("state", {})["user"] = "b:" + hashlib.sha256(token.encode()).hexdigest()[:32]
        # Behind Fly's proxy (or any HTTPS proxy) the server itself sees plain HTTP.
        https = scope.get("scheme") == "https" or headers.get("x-forwarded-proto") == "https"
        set_cookie = (f"{COOKIE}={token}; Max-Age={COOKIE_MAX_AGE_S}; Path=/; HttpOnly; SameSite=Lax"
                      + ("; Secure" if https else ""))

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (b"set-cookie", set_cookie.encode("latin-1"))]
            await send(message)

        await self.app(scope, receive, send_with_cookie)


def _read_cookie(header: str) -> str | None:
    try:
        morsel = SimpleCookie(header).get(COOKIE)
    except Exception:  # a malformed Cookie header from somewhere else on this domain
        return None
    return morsel.value if morsel and _TOKEN.fullmatch(morsel.value) else None
