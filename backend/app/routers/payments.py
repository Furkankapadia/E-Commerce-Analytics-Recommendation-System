from fastapi import APIRouter, HTTPException
from ..services.analytics import get_payment_analytics

router = APIRouter(prefix="/payments", tags=["Payments"])

@router.get("/")
def read_payment_analytics():
    try:
        return get_payment_analytics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
