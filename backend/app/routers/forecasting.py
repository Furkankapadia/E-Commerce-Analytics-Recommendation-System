from fastapi import APIRouter, HTTPException
from ..services.forecaster import generate_sales_forecast

router = APIRouter(prefix="/forecasting", tags=["Forecasting"])

@router.get("/")
def read_sales_forecast():
    try:
        return generate_sales_forecast()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
