from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_admin
from app import models, schemas

router = APIRouter(prefix="/players", tags=["players"])


@router.get("", response_model=list[schemas.PlayerOut])
def list_players(
    team: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),  # any logged-in user can view
):
    return (
        db.query(models.Player)
        .filter(models.Player.team_name == team)
        .order_by(models.Player.jersey_number)
        .all()
    )


@router.post("", response_model=schemas.PlayerOut)
def add_player(
    payload: schemas.PlayerCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),  # blocked for non-admins
):
    player = models.Player(**payload.model_dump(), created_by=current_user.username)
    db.add(player)
    db.commit()
    db.refresh(player)
    return player


@router.put("/{player_id}", response_model=schemas.PlayerOut)
def update_player(
    player_id: int,
    payload: schemas.PlayerCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),  # blocked for non-admins
):
    player = db.query(models.Player).get(player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    for field, value in payload.model_dump().items():
        setattr(player, field, value)
    db.commit()
    db.refresh(player)
    return player


@router.delete("/{player_id}")
def delete_player(
    player_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),  # blocked for non-admins
):
    player = db.query(models.Player).get(player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    db.delete(player)
    db.commit()
    return {"deleted": True}
