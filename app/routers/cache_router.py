"""Cache inspection and management endpoints."""
from fastapi import APIRouter
from app.cache import cache

router = APIRouter(prefix="/api/cache", tags=["cache"])


@router.get("/stats")
def cache_stats():
    return cache.stats()


@router.delete("/clear")
def clear_cache():
    n = cache.clear()
    return {"cleared": n}
