from fastapi import APIRouter, Query, HTTPException
from typing import List, Dict, Any
from ..services.recommender import get_category_recommendations, get_all_association_rules

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])

@router.get("/rules")
def read_all_rules(limit: int = Query(50, description="Max rules to return")):
    try:
        return get_all_association_rules(limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/category")
def read_category_recommendations(
    category_name: str = Query(..., description="English category name (e.g. telephony, baby, auto)"),
    limit: int = Query(5, description="Number of items to recommend")
):
    try:
        recommendations = get_category_recommendations(category_name, limit)
        if not recommendations:
            return {
                "message": f"No recommendations found for '{category_name}'. Try category names like 'telephony', 'baby', 'auto', 'cool_stuff'.",
                "recommendations": []
            }
        return {
            "category": category_name,
            "recommendations": recommendations
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
