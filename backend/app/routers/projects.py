"""
backend/app/routers/projects.py
Project CRUD + API key generation.
"""
import hashlib, secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..database import get_db
from ..models import Project, ApiKey
from ..schemas import ProjectCreate, ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    existing = db.execute(
        select(Project).where(Project.slug == body.slug)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"Slug '{body.slug}' already taken")

    project = Project(**body.model_dump())
    db.add(project)
    db.flush()

    # Auto-create first API key
    raw_key = f"tok_live_{secrets.token_urlsafe(24)}"
    api_key = ApiKey(
        project_id=project.id,
        key_hash=_hash_key(raw_key),
        prefix=raw_key[:12],
        label="Default",
    )
    db.add(api_key)
    db.commit()
    db.refresh(project)

    # Return project + raw key (only shown once)
    return {**project.__dict__, "_api_key": raw_key}


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.execute(select(Project).where(Project.active == True)).scalars().all()


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    p.active = False
    db.commit()
