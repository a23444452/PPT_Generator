"""API 路由聚合：main.py 只需 include 這裡的單一 router。"""

from fastapi import APIRouter

from app.api import pipeline, projects

router = APIRouter(prefix="/api")
router.include_router(projects.router)
router.include_router(pipeline.router)

__all__ = ["router"]
