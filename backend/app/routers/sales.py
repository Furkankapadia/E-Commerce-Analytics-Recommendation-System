from fastapi import APIRouter, HTTPException
from ..services.analytics import get_sales_analytics

router = APIRouter(prefix="/sales", tags=["Sales"])

@router.get("/")
def read_sales_analytics():
    try:
        return get_sales_analytics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
