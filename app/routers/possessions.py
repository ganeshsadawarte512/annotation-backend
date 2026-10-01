from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_admin
from app import models, schemas

router = APIRouter(tags=["possessions"])


@router.get("/games/{game_id}/possessions", response_model=list[schemas.PossessionOut])
def list_possessions(
    game_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),  # any logged-in user can view
):
    return (
        db.query(models.Possession)
        .filter(models.Possession.game_id == game_id)
        .order_by(models.Possession.quarter, models.Possession.id)
        .all()
    )


@router.post("/games/{game_id}/possessions", response_model=schemas.PossessionOut)
def add_possession(
    game_id: int,
    payload: schemas.PossessionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),  # admin or annotator can log plays
):
    game = db.query(models.Game).get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    data = payload.model_dump()
    actions_data = data.pop("actions", [])
    poss = models.Possession(game_id=game_id, **data, created_by=current_user.username)
    for i, a in enumerate(actions_data):
        poss.actions.append(models.PossessionAction(sort_order=i, **a))
    db.add(poss)
    db.commit()
    db.refresh(poss)
    return poss


@router.put("/possessions/{possession_id}", response_model=schemas.PossessionOut)
def update_possession(
    possession_id: int,
    payload: schemas.PossessionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),  # admin or annotator can edit plays
):
    poss = db.query(models.Possession).get(possession_id)
    if not poss:
        raise HTTPException(status_code=404, detail="Possession not found")
    data = payload.model_dump()
    actions_data = data.pop("actions", [])
    for field, value in data.items():
        setattr(poss, field, value)
    poss.actions.clear()  # cascade="all, delete-orphan" removes the old rows on commit
    for i, a in enumerate(actions_data):
        poss.actions.append(models.PossessionAction(sort_order=i, **a))
    db.commit()
    db.refresh(poss)
    return poss


@router.delete("/possessions/{possession_id}")
def delete_possession(
    possession_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),  # blocked for non-admins
):
    poss = db.query(models.Possession).get(possession_id)
    if not poss:
        raise HTTPException(status_code=404, detail="Possession not found")
    db.delete(poss)
    db.commit()
    return {"deleted": True}


@router.delete("/games/{game_id}/possessions")
def delete_all_possessions(
    game_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),  # blocked for non-admins
):
    """Wipe every possession logged for a game — e.g. to redo a bad JSON
    import or start a manual annotation pass over from scratch."""
    game = db.query(models.Game).get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    poss_ids = [
        pid for (pid,) in
        db.query(models.Possession.id).filter(models.Possession.game_id == game_id).all()
    ]
    if poss_ids:
        # SQLite doesn't enforce FK cascades here, so child action rows need
        # to be cleared explicitly before the bulk delete on possessions.
        db.query(models.PossessionAction).filter(
            models.PossessionAction.possession_id.in_(poss_ids)
        ).delete(synchronize_session=False)
    deleted = (
        db.query(models.Possession)
        .filter(models.Possession.game_id == game_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": deleted}
