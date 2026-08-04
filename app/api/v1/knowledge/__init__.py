from app.api.v1.knowledge.articles import router as articles_router
from app.api.v1.knowledge.categories import router as categories_router
from app.api.v1.knowledge.tags import router as tags_router

__all__ = [
    "articles_router",
    "categories_router",
    "tags_router",
]
