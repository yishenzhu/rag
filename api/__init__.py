from .embedding import embedding_router
from .knowledge_base import knowledge_router
from .memory_bank import memory_router
from fastapi import APIRouter

router = APIRouter()
router.include_router(knowledge_router)
router.include_router(memory_router)
router.include_router(embedding_router)
