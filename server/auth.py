"""Who is making this request?

Every route depends on current_user(), and every row in the database is scoped to the id it returns.

For now there are no accounts: the server is meant to run for one person (on your own machine, or
behind something that already restricts access), so everyone is "local". To host it for many people,
replace this with a real check (a session cookie, an OAuth token, a reverse proxy's auth header, ...)
that returns that user's id, or raises HTTPException(401).
"""

from __future__ import annotations

from fastapi import Request


def current_user(request: Request) -> str:
    return "local"
