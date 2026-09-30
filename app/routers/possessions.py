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
    poss = models.Possession(
        game_id=game_id, **payload.model_dump(), created_by=current_user.username
    )
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
    for field, value in payload.model_dump().items():
        setattr(poss, field, value)
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


# ---------- Events (multiple plays within one possession) ----------

@router.post("/possessions/{possession_id}/events", response_model=schemas.PossessionEventOut)
def add_event(
    possession_id: int,
    payload: schemas.PossessionEventCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),  # admin or annotator
):
    poss = db.query(models.Possession).get(possession_id)
    if not poss:
        raise HTTPException(status_code=404, detail="Possession not found")
    if payload.action not in models.POSSESSION_EVENT_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"action must be one of: {', '.join(models.POSSESSION_EVENT_ACTIONS)}",
        )
    event = models.PossessionEvent(
        possession_id=possession_id, **payload.model_dump(), created_by=current_user.username
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.put("/possession-events/{event_id}", response_model=schemas.PossessionEventOut)
def update_event(
    event_id: int,
    payload: schemas.PossessionEventCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),  # admin or annotator
):
    event = db.query(models.PossessionEvent).get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if payload.action not in models.POSSESSION_EVENT_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"action must be one of: {', '.join(models.POSSESSION_EVENT_ACTIONS)}",
        )
    for field, value in payload.model_dump().items():
        setattr(event, field, value)
    db.commit()
    db.refresh(event)
    return event


@router.delete("/possession-events/{event_id}")
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),  # admin or annotator
):
    event = db.query(models.PossessionEvent).get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    db.delete(event)
    db.commit()
    return {"deleted": True}
