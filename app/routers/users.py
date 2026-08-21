from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.security import hash_password
from app import models, schemas

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[schemas.UserOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),  # blocked for non-admins
):
    return db.query(models.User).order_by(models.User.username).all()


@router.post("", response_model=schemas.UserOut)
def create_user(
    payload: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),  # blocked for non-admins
):
    if db.query(models.User).filter(models.User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="That username is already taken.")
    role = payload.role if payload.role in ("admin", "annotator") else "annotator"
    user = models.User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),  # blocked for non-admins
):
    """Deactivates an account rather than deleting it outright, so their
    past work (games/possessions created_by them) still makes sense."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't deactivate your own account.")
    user = db.query(models.User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    db.commit()
    return {"deactivated": True}
