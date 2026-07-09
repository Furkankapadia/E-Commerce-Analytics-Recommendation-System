from fastapi import APIRouter, HTTPException
from ..services.analytics import get_review_analytics

router = APIRouter(prefix="/reviews", tags=["Reviews"])

@router.get("/")
def read_review_analytics():
    try:
        return get_review_analytics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
