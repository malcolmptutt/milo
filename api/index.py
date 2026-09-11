"""
MiLO PoC backend.

A single FastAPI app, deployed as one Vercel Function, handling:
  - Google OAuth login (so the user can connect their Google account)
  - Reading and creating events on the user's Google Calendar
  - A simple task list backed by Postgres

Vercel routes every request under /api/* to this file (see vercel.json).
FastAPI's own routing then dispatches to the handlers below.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature

import db

app = FastAPI(title="MiLO API")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-secret-change-me")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "/")

# Full calendar scope (not read-only) so the PoC can also create events.
SCOPES = "openid email profile https://www.googleapis.com/auth/calendar"

serializer = URLSafeTimedSerializer(SESSION_SECRET)
COOKIE_MAX_AGE = 60 * 60 * 24 * 14  # 14 days


def create_session_cookie(user_id: str) -> str:
    return serializer.dumps({"user_id": user_id})


def read_session(request: Request):
    cookie = request.cookies.get("milo_session")
    if not cookie:
        return None
    try:
        data = serializer.loads(cookie, max_age=COOKIE_MAX_AGE)
        return data.get("user_id")
    except BadSignature:
        return None


def require_session(request: Request) -> str:
    user_id = read_session(request)
    if not user_id:
        raise HTTPException(401, "Not signed in")
    return user_id


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------

@app.get("/api/auth/google/login")
def google_login():
    if not GOOGLE_CLIENT_ID or not REDIRECT_URI:
        raise HTTPException(500, "Google OAuth is not configured on the server")
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    resp = RedirectResponse(url)
    resp.set_cookie("milo_oauth_state", state, httponly=True, max_age=600, samesite="lax")
    return resp


@app.get("/api/auth/google/callback")
async def google_callback(request: Request, code: str = None, state: str = None, error: str = None):
    if error:
        return RedirectResponse(f"{FRONTEND_URL}?auth_error={error}")

    stored_state = request.cookies.get("milo_oauth_state")
    if not code or not state or state != stored_state:
        raise HTTPException(400, "Invalid OAuth state")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()

        userinfo_resp = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        userinfo_resp.raise_for_status()
        profile = userinfo_resp.json()

    expiry = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
    user_id = db.upsert_user(
        google_sub=profile["sub"],
        email=profile.get("email", ""),
        name=profile.get("name", ""),
        picture=profile.get("picture", ""),
    )
    db.save_tokens(
        user_id=user_id,
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
        expiry=expiry,
        scope=tokens.get("scope", ""),
    )

    resp = RedirectResponse(FRONTEND_URL)
    resp.set_cookie(
        "milo_session",
        create_session_cookie(user_id),
        httponly=True,
        max_age=COOKIE_MAX_AGE,
        samesite="lax",
        secure=True,
    )
    resp.delete_cookie("milo_oauth_state")
    return resp


@app.post("/api/auth/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("milo_session")
    return resp


@app.get("/api/auth/me")
def me(request: Request):
    user_id = read_session(request)
    if not user_id:
        return JSONResponse({"authenticated": False})
    user = db.get_user(user_id)
    if not user:
        return JSONResponse({"authenticated": False})
    return {"authenticated": True, "user": user}


async def get_valid_access_token(user_id: str) -> str:
    token_row = db.get_tokens(user_id)
    if not token_row:
        raise HTTPException(401, "Google account not connected")

    if token_row["expiry"] > datetime.now(timezone.utc) + timedelta(seconds=60):
        return token_row["access_token"]

    if not token_row["refresh_token"]:
        raise HTTPException(401, "Google session expired, please reconnect")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": token_row["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        new_tokens = resp.json()

    new_expiry = datetime.now(timezone.utc) + timedelta(seconds=new_tokens.get("expires_in", 3600))
    db.save_tokens(
        user_id=user_id,
        access_token=new_tokens["access_token"],
        refresh_token=token_row["refresh_token"],
        expiry=new_expiry,
        scope=token_row["scope"],
    )
    return new_tokens["access_token"]


# ---------------------------------------------------------------------
# Google Calendar
# ---------------------------------------------------------------------

@app.get("/api/calendar/events")
async def list_events(request: Request):
    user_id = require_session(request)
    access_token = await get_valid_access_token(user_id)

    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=7)
    params = {
        "timeMin": now.isoformat(),
        "timeMax": time_max.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "20",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )
        resp.raise_for_status()

    events = resp.json().get("items", [])
    return {
        "events": [
            {
                "id": e["id"],
                "title": e.get("summary", "(no title)"),
                "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date")),
                "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date")),
            }
            for e in events
        ]
    }


@app.post("/api/calendar/events")
async def create_event(request: Request):
    user_id = require_session(request)
    body = await request.json()
    access_token = await get_valid_access_token(user_id)

    event_payload = {
        "summary": body.get("title", "Untitled"),
        "start": {"dateTime": body["start"]},
        "end": {"dateTime": body["end"]},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {access_token}"},
            json=event_payload,
        )
        resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------

@app.get("/api/tasks")
def list_tasks(request: Request):
    user_id = require_session(request)
    return {"tasks": db.list_tasks(user_id)}


@app.post("/api/tasks")
async def create_task(request: Request):
    user_id = require_session(request)
    body = await request.json()
    if not body.get("title"):
        raise HTTPException(400, "title is required")
    task = db.create_task(
        user_id=user_id,
        title=body["title"],
        category=body.get("category", "business"),
        due_at=body.get("due_at"),
    )
    return task


@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: str, request: Request):
    user_id = require_session(request)
    body = await request.json()
    task = db.update_task(task_id, user_id, **body)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str, request: Request):
    user_id = require_session(request)
    db.delete_task(task_id, user_id)
    return {"ok": True}
