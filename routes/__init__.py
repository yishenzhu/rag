from .knowledge_base import knowledge_router
from .memory_bank import memory_router
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()
router.include_router(knowledge_router)
router.include_router(memory_router)


@router.get("/health")
async def health():
    return JSONResponse({"status": "ok", "service": "rag-api"})
