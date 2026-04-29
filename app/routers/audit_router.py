"""
Audit endpoints.

POST /api/audit/corp     — start a corp audit job
POST /api/audit/alliance — start an alliance-wide audit job
GET  /api/corps          — list all SoB corps (requires saved credentials)
GET  /api/reports/{name} — download a generated PDF
WS   /ws/{job_id}        — stream progress messages for a running job
"""
from __future__ import annotations

import asyncio
import queue
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.audit import collect_corp, collect_alliance
from app.config import ENV_FILE, REPORTS_DIR
from app.providers import EXTRA_PROVIDERS
from app.providers.auth_scraper import AllianceAuthProvider
from app.providers.esi import ESIProvider
from app.report.pdf import build_corp_pdf, build_alliance_pdf

router = APIRouter(tags=["audit"])

# Thread pool for blocking audit tasks
_executor = ThreadPoolExecutor(max_workers=4)

# In-memory job registry: job_id → {queue, status, result_file}
_jobs: dict[str, dict] = {}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _safe_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_").lower() or "report"


def _load_provider() -> AllianceAuthProvider:
    """Read Auth.env and return an authenticated provider."""
    if not ENV_FILE.exists():
        raise HTTPException(status_code=401, detail="No credentials saved. Configure them first.")
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

    cookie = env.get("SESSION_COOKIE", "")
    sid  = re.search(r"sessionid=([^;\s]+)", cookie)
    csrf = re.search(r"csrftoken=([^;\s]+)", cookie)
    if not sid or not csrf:
        sid_v  = env.get("SESSIONID", "")
        csrf_v = env.get("CSRFTOKEN", "")
        if not sid_v or not csrf_v:
            raise HTTPException(status_code=401, detail="Credentials incomplete — re-save them.")
        return AllianceAuthProvider(sid_v, csrf_v)
    return AllianceAuthProvider(sid.group(1), csrf.group(1))


def _new_job() -> tuple[str, "queue.Queue"]:
    job_id = str(uuid.uuid4())[:8]
    q: "queue.Queue" = queue.Queue()
    _jobs[job_id] = {"queue": q, "status": "running", "result_file": None}
    return job_id, q


# ─── Models ───────────────────────────────────────────────────────────────────

class CorpAuditRequest(BaseModel):
    corp_id: int
    corp_name: str
    year: int = date.today().year


class AllianceAuditRequest(BaseModel):
    year: int = date.today().year


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/api/corps")
def list_corps():
    auth = _load_provider()
    today = date.today()
    try:
        corps = auth.list_alliance_corps(today.year, today.month)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return [{"id": cid, "name": name} for cid, name in corps]


@router.post("/api/audit/corp")
async def start_corp_audit(req: CorpAuditRequest):
    auth = _load_provider()
    esi  = ESIProvider()
    job_id, q = _new_job()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    def log(msg: str, tag: str = "white"):
        q.put({"msg": msg, "tag": tag})

    def _run():
        try:
            corp = collect_corp(
                auth, esi, EXTRA_PROVIDERS,
                req.corp_id, req.corp_name, req.year, log,
            )
            fname = f"sob_corp_{_safe_filename(req.corp_name)}_{date.today()}.pdf"
            out   = REPORTS_DIR / fname
            build_corp_pdf(req.corp_name, corp.members, req.year, out)
            _jobs[job_id]["result_file"] = fname
            _jobs[job_id]["status"] = "done"
            q.put({"msg": f"[✓] Report ready: {fname}", "tag": "green"})
        except Exception as e:
            _jobs[job_id]["status"] = "error"
            q.put({"msg": f"[!] {e}", "tag": "red"})
        finally:
            q.put(None)  # sentinel

    asyncio.get_event_loop().run_in_executor(_executor, _run)
    return {"job_id": job_id}


@router.post("/api/audit/alliance")
async def start_alliance_audit(req: AllianceAuditRequest):
    auth = _load_provider()
    esi  = ESIProvider()
    job_id, q = _new_job()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    def log(msg: str, tag: str = "white"):
        q.put({"msg": msg, "tag": tag})

    def _run():
        try:
            corps = collect_alliance(auth, esi, EXTRA_PROVIDERS, req.year, log)
            fname = f"sob_alliance_{date.today()}.pdf"
            out   = REPORTS_DIR / fname
            build_alliance_pdf(corps, req.year, out)
            _jobs[job_id]["result_file"] = fname
            _jobs[job_id]["status"] = "done"
            total = sum(len(c.members) for c in corps)
            q.put({"msg": f"[★] Alliance report ready: {fname}  ({len(corps)} corps, {total} mains)", "tag": "gold"})
        except Exception as e:
            _jobs[job_id]["status"] = "error"
            q.put({"msg": f"[!] {e}", "tag": "red"})
        finally:
            q.put(None)

    asyncio.get_event_loop().run_in_executor(_executor, _run)
    return {"job_id": job_id}


@router.get("/api/reports/{filename}")
def download_report(filename: str):
    path = REPORTS_DIR / filename
    if not path.exists() or path.suffix != ".pdf":
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(path, media_type="application/pdf", filename=filename)


# ─── WebSocket progress stream ────────────────────────────────────────────────

@router.websocket("/ws/{job_id}")
async def ws_progress(websocket: WebSocket, job_id: str):
    await websocket.accept()
    if job_id not in _jobs:
        await websocket.send_json({"msg": "Job not found.", "tag": "red"})
        await websocket.close()
        return

    q = _jobs[job_id]["queue"]
    try:
        while True:
            try:
                msg = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            if msg is None:  # sentinel — job finished
                result_file = _jobs[job_id].get("result_file")
                await websocket.send_json({"done": True, "file": result_file})
                break

            await websocket.send_json(msg)
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()
        _jobs.pop(job_id, None)
