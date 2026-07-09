from fastapi import APIRouter, HTTPException
from ..services.analytics import get_product_analytics

router = APIRouter(prefix="/products", tags=["Products"])

@router.get("/")
def read_product_analytics():
    try:
        return get_product_analytics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
