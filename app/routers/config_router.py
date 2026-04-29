"""Credentials management — read/write Auth.env via the web UI."""
from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import ENV_FILE

router = APIRouter(prefix="/api/config", tags=["config"])


class Credentials(BaseModel):
    session_id: str
    csrf_token: str


@router.get("/credentials")
def get_credentials():
    """Return whether credentials are configured (never returns the raw values)."""
    if not ENV_FILE.exists():
        return {"configured": False}
    try:
        text = ENV_FILE.read_text()
        has_session = bool(re.search(r"sessionid=\S+", text))
        has_csrf    = bool(re.search(r"csrftoken=\S+",  text))
        return {"configured": has_session and has_csrf}
    except Exception:
        return {"configured": False}


@router.post("/credentials")
def save_credentials(creds: Credentials):
    """Write sessionid + csrftoken to Auth.env."""
    if not creds.session_id or not creds.csrf_token:
        raise HTTPException(status_code=400, detail="Both session_id and csrf_token are required.")
    cookie = f"sessionid={creds.session_id}; csrftoken={creds.csrf_token}"
    ENV_FILE.write_text(
        f'# Saved by SoB Audit web UI on {date.today()}\n'
        f'SESSION_COOKIE="{cookie}"\n'
    )
    return {"ok": True}
