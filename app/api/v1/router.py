from fastapi import APIRouter

from app.api.v1.assignments import router as assignments_router
from app.api.v1.auth import router as auth_router
from app.api.v1.companies import router as companies_router
from app.api.v1.employees import router as employees_router
from app.api.v1.knowledge.articles import router as knowledge_articles_router
from app.api.v1.knowledge.categories import router as knowledge_categories_router
from app.api.v1.knowledge.tags import router as knowledge_tags_router
from app.api.v1.programs import router as programs_router
from app.api.v1.progress import router as progress_router
from app.api.v1.steps import router as steps_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(companies_router)
router.include_router(employees_router)
router.include_router(programs_router)
router.include_router(steps_router)
router.include_router(assignments_router)
router.include_router(progress_router)
router.include_router(knowledge_articles_router)
router.include_router(knowledge_categories_router)
router.include_router(knowledge_tags_router)
