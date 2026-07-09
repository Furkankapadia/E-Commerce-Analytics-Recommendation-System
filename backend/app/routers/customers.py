from fastapi import APIRouter, HTTPException
from ..services.analytics import get_customer_analytics

router = APIRouter(prefix="/customers", tags=["Customers"])

@router.get("/")
def read_customer_analytics():
    try:
        return get_customer_analytics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
