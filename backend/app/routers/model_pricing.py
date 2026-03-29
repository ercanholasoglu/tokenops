"""
backend/app/routers/model_pricing.py
Model pricing registry — list, lookup, update.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..database import get_db
from ..models import ModelPricing
from ..schemas import ModelPricingOut

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelPricingOut])
def list_models(db: Session = Depends(get_db)):
    return db.execute(select(ModelPricing)).scalars().all()


@router.get("/{model_name}", response_model=ModelPricingOut)
def get_model(model_name: str, db: Session = Depends(get_db)):
    m = db.execute(
        select(ModelPricing).where(ModelPricing.model == model_name)
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(404, f"Model '{model_name}' not in pricing registry")
    return m
