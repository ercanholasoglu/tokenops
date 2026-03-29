"""
backend/app/middleware/auth.py
API key authentication dependency.
SDK sends:  Authorization: Bearer tok_live_xxxx
"""
import hashlib
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime

from ..database import get_db
from ..models import ApiKey, Project

bearer = HTTPBearer()


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def get_project_from_key(
    credentials: HTTPAuthorizationCredentials = Security(bearer),
    db: Session = Depends(get_db),
) -> Project:
    """
    Validates the Bearer token, returns the associated Project.
    Used as a FastAPI dependency on protected routes.
    """
    raw_key = credentials.credentials
    key_hash = _hash_key(raw_key)

    api_key = db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.active == True)
    ).scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid or expired API key")

    # Update last_used
    api_key.last_used = datetime.utcnow()
    db.commit()

    return api_key.project
