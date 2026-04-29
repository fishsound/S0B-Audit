"""
SONS of BANE — Alliance Audit Web App
======================================
Run with:  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
Then open: http://localhost:8000
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import REPORTS_DIR, STATIC_DIR
from app.routers.audit_router import router as audit_router
from app.routers.cache_router import router as cache_router
from app.routers.config_router import router as config_router

REPORTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="SoB Audit",
    description="SONS of BANE Alliance Auth Compliance Audit Tool",
    version="2.0.0",
)

app.include_router(audit_router)
app.include_router(cache_router)
app.include_router(config_router)

# Serve the single-page frontend from /static/
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
