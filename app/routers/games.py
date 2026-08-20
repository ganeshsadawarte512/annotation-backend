from typing import Optional
import json as json_lib

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.storage import get_storage
from app import models, schemas

router = APIRouter(prefix="/games", tags=["games"])


@router.get("", response_model=list[schemas.GameOut])
def list_games(
    team: Optional[str] = None,
    from_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),  # any logged-in user can view
):
    query = db.query(models.Game)
    if team:
        like = f"%{team}%"
        query = query.filter(
            (models.Game.home_team.ilike(like)) | (models.Game.visitor_team.ilike(like))
        )
    if from_date:
        query = query.filter(models.Game.date >= from_date)
    return query.order_by(models.Game.date.desc()).all()


@router.post("", response_model=schemas.GameOut)
def create_game(
    payload: schemas.GameCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),  # blocked for non-admins
):
    game = models.Game(**payload.model_dump(), created_by=current_user.username)
    db.add(game)
    db.commit()
    db.refresh(game)
    return game


@router.patch("/{game_id}", response_model=schemas.GameOut)
def update_game(
    game_id: int,
    payload: schemas.GameUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),  # any logged-in user — role-gated below
):
    game = db.query(models.Game).get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    data = payload.model_dump(exclude_unset=True)

    # Core game info (date/teams) can only be changed by an admin — this is
    # the "manage the whole game record" capability, distinct from the
    # day-to-day status checkboxes any logged-in user can tick.
    core_fields = {"date", "home_team", "home_team_id", "visitor_team", "visitor_team_id", "mf"}
    if core_fields & data.keys() and current_user.role != models.UserRole.admin:
        raise HTTPException(
            status_code=403,
            detail="Only Admin accounts can edit a game's core details (date/teams).",
        )
    for field in core_fields:
        if field in data:
            setattr(game, field, data[field])

    # Checking "Complete" or "QA" stamps the current user's name automatically;
    # unchecking it clears that name again. Any logged-in user can do this.
    if "is_complete" in data:
        game.is_complete = data["is_complete"]
        game.complete_by = current_user.username if data["is_complete"] else None
    if "is_qa_done" in data:
        game.is_qa_done = data["is_qa_done"]
        game.qa_by = current_user.username if data["is_qa_done"] else None

    for field in ("in_process", "clock_vid_ok", "has_video_error", "has_annotation_error", "notes"):
        if field in data:
            setattr(game, field, data[field])

    db.commit()
    db.refresh(game)
    return game


@router.delete("/{game_id}")
def delete_game(
    game_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),  # blocked for non-admins
):
    game = db.query(models.Game).get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    db.delete(game)  # cascades to delete its possessions too (see models.py relationship)
    db.commit()
    return {"deleted": True}


@router.get("/{game_id}", response_model=schemas.GameOut)
def get_game(game_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    game = db.query(models.Game).get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


@router.post("/{game_id}/video", response_model=schemas.GameOut)
def upload_video(
    game_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),  # blocked for non-admins
):
    game = db.query(models.Game).get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    storage = get_storage()
    path = storage.save(file, game.game_uid)
    game.video_path = path
    game.video_status = "uploaded"
    db.commit()
    db.refresh(game)
    return game


@router.get("/{game_id}/export")
def export_game_json(
    game_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),  # any logged-in user can download
):
    """One JSON file per game: the game record plus every possession logged
    for it, in one document. This is the 'J' column download on the dashboard."""
    game = db.query(models.Game).get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    possessions = (
        db.query(models.Possession)
        .filter(models.Possession.game_id == game_id)
        .order_by(models.Possession.quarter, models.Possession.id)
        .all()
    )

    def poss_to_dict(p):
        d = {c.name: getattr(p, c.name) for c in p.__table__.columns}
        d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
        if d.get("ball_screens"):
            try:
                d["ball_screens"] = json_lib.loads(d["ball_screens"])
            except (ValueError, TypeError):
                pass  # leave as raw string if it wasn't valid JSON
        return d

    game_dict = {c.name: getattr(game, c.name) for c in game.__table__.columns}
    game_dict["created_at"] = game_dict["created_at"].isoformat() if game_dict.get("created_at") else None

    payload = {
        "game": game_dict,
        "possession_count": len(possessions),
        "possessions": [poss_to_dict(p) for p in possessions],
    }
    content = json_lib.dumps(payload, indent=2, default=str)
    safe_name = f"{game.home_team}_vs_{game.visitor_team}_{game.date}".replace(" ", "_").replace("/", "-")
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'},
    )
