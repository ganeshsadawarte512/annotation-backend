from typing import Optional
import json as json_lib
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.storage import get_storage
from app import models, schemas

router = APIRouter(prefix="/games", tags=["games"])


# ---------- Pre-annotated game import (ShotTracker-style export) ----------
# Maps the vendor's shot-attribute / scheme codes onto the labels our own
# dropdowns use, so imported data lines up with what an annotator would have
# picked by hand.
_SHOT_TYPE_MAP = {
    "JUMPSHOT": "JumpShot", "PULLUPJUMPSHOT": "JumpShot",
    "DRIVINGLAYUP": "DriveLayup", "LAYUP": "Layup",
    "TIPIN": "Tipin", "TIPINLAYUP": "Tipin",
    "DUNK": "Dunk", "STEPBACKJUMPSHOT": "Stepback/Sidestep jumper",
    "TURNAROUNDJUMPSHOT": "Turnaround Jumper", "HOOKSHOT": "Hook",
    "FLOATINGJUMPSHOT": "Floater", "ALLEYOOP": "Alleyoop",
}
_DIRECTION_MAP = {"DIRECTIONLEFT": "Left", "DIRECTIONRIGHT": "Right"}
_OFFENSE_MAP = {
    "motion": "Motion", "transition": "Transaction", "dribbledrive": "Dribble Drive",
    "flex": "Flex", "floppy": "Floppy", "highlow": "High-Low", "horn": "Horn",
    "isolation": "Isolation", "iverson": "Iverson", "princeton": "Princeton/Backdoor",
    "backdoor": "Princeton/Backdoor", "spread": "Spread",
}
_DEFENSE_MAP = {
    "mantoman": "Man-to-Man", "fullcourtmantoman": "Full-Court Man-to-Man",
    "halfcourtpress": "Half-Court Pressing Man-to-Man", "zone": "Zone",
    "zone131": "1-3-1 Zone", "zone23": "2-3 Zone", "zone32": "3-2 Zone",
    "matchupzone": "Matchup Zone", "boxandone": "Box-and-1 Defense",
    "triangleandtwo": "Triangle-and-2 Defense",
}
# Action codes that already match our Action dropdown exactly (AST, STL, LBTO,
# DEFENSIVE_REB, OFFENSIVE_REB, FLDN, FT, FTA) pass through untouched below;
# only FG/FGA need translating, since the vendor splits makes vs misses into
# separate event types instead of an action+result pair.
_RESULT_BY_ACTION = {
    "OFFENSIVE_REB": "Offensive",
    "DEFENSIVE_REB": "Defensive",
    "LBTO": "Lost Ball",
    "FT": "Make",
    "FTA": "Miss",
}


def _parse_period_to_quarter(period: Optional[str]) -> int:
    """'H1' -> 1, 'H2' -> 2, 'OT1' -> 5, etc. Falls back to 1 if unparseable."""
    if not period:
        return 1
    period = period.upper()
    digits = "".join(ch for ch in period if ch.isdigit())
    n = int(digits) if digits else 1
    return 4 + n if period.startswith("OT") else n


def _clean_shot_clock(raw) -> Optional[str]:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val <= 0:
        return None
    return f"{min(val, 30):.1f}"


def _format_players(player_ids, player_lookup: dict) -> Optional[str]:
    """Turns a list of vendor player ids into the '#num Name' comma-joined
    text our on-court checkboxes match against (see rosterForTeam() in the
    frontend). Ids with no roster match are skipped rather than guessed at."""
    labels = []
    for pid in player_ids or []:
        info = player_lookup.get(str(pid))
        if info and info.get("jersey") and info.get("name"):
            labels.append(f"#{info['jersey']} {info['name']}")
    return ", ".join(labels) if labels else None


@router.post("/import-json")
def import_game_json(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),  # blocked for non-admins
):
    """Import a pre-annotated game export. Matches an existing Game by its
    H/ID + V/ID (set manually when the game was added) and the game date;
    if none matches, a new Game row is created from the file itself."""
    try:
        raw = json_lib.loads(file.file.read())
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="That file isn't valid JSON.")

    try:
        game_body = raw["gameDetails"]["retBody"]
        video_body = raw.get("videoDetails", {}) or {}
        possessions_raw = raw["possessions"]
        roster_home = (raw.get("rosterHome") or {}).get("retBody", {}) or {}
        roster_away = (raw.get("rosterAway") or {}).get("retBody", {}) or {}
    except (KeyError, TypeError):
        raise HTTPException(
            status_code=400,
            detail="Unrecognized JSON shape — expected gameDetails, videoDetails, "
                   "rosterHome, rosterAway, and possessions.",
        )

    team1_id, team2_id = str(game_body.get("team1Id")), str(game_body.get("team2Id"))
    team1_name, team2_name = game_body.get("team1Name"), game_body.get("team2Name")
    home_id = str(game_body.get("homeTeamId") or team1_id)
    if home_id == team1_id:
        home_team, home_team_id = team1_name, team1_id
        visitor_team, visitor_team_id = team2_name, team2_id
    else:
        home_team, home_team_id = team2_name, team2_id
        visitor_team, visitor_team_id = team1_name, team1_id

    date_str = (video_body.get("gameDate") or "")[:10] or None
    mf = "F" if (game_body.get("gender") or "").upper().startswith("W") else "M"

    # Player id -> jersey/name/team, built from both rosters. Also
    # auto-provisions each team's Player rows so on-court checkboxes work
    # immediately after import, without a separate manual roster-entry step.
    team_names_by_id = {home_team_id: home_team, visitor_team_id: visitor_team}
    player_lookup = {}
    for roster in (roster_home, roster_away):
        roster_team_id = str((roster.get("team") or {}).get("id", ""))
        team_name = team_names_by_id.get(roster_team_id) or (roster.get("team") or {}).get("name")
        for p in roster.get("players", []):
            jersey = p.get("jerseyNumberStr") or str(p.get("jerseyNumber", ""))
            name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
            player_lookup[str(p.get("id"))] = {"jersey": jersey, "name": name}
            if team_name and jersey and name:
                exists = (
                    db.query(models.Player)
                    .filter_by(team_name=team_name, jersey_number=jersey)
                    .first()
                )
                if not exists:
                    db.add(models.Player(
                        team_name=team_name, jersey_number=jersey, player_name=name,
                        created_by=current_user.username,
                    ))
    db.flush()

    def team_name_for(team_id):
        team_id = str(team_id)
        if team_id == home_team_id:
            return home_team
        if team_id == visitor_team_id:
            return visitor_team
        return team_id

    # Match an existing (likely manually-created) Game by its H/ID + V/ID —
    # in either home/visitor orientation — and date; else create a new one.
    game = None
    if date_str:
        game = (
            db.query(models.Game)
            .filter(
                models.Game.date == date_str,
                or_(
                    and_(models.Game.home_team_id == home_team_id, models.Game.visitor_team_id == visitor_team_id),
                    and_(models.Game.home_team_id == visitor_team_id, models.Game.visitor_team_id == home_team_id),
                ),
            )
            .first()
        )
    if not game:
        game = models.Game(
            game_uid=str(game_body.get("id") or uuid.uuid4()),
            date=date_str or "",
            mf=mf,
            home_team=home_team, home_team_id=home_team_id,
            visitor_team=visitor_team, visitor_team_id=visitor_team_id,
            created_by=current_user.username,
        )
        db.add(game)
        db.flush()

    created, skipped, failed = 0, 0, []
    for idx, item in enumerate(possessions_raw):
        # Each possession gets its own SAVEPOINT: if something about this one
        # record is malformed, only its own insert rolls back — the rest of
        # the batch still imports instead of the whole request dying silently.
        try:
            with db.begin_nested():
                quarter = _parse_period_to_quarter(item.get("period"))
                start_time = item.get("startGameClock")
                end_time = item.get("endGameClock")

                # Idempotent re-import: skip a possession already pulled in before.
                dup = (
                    db.query(models.Possession)
                    .filter_by(game_id=game.id, quarter=quarter, start_time=start_time, end_time=end_time)
                    .first()
                )
                if dup:
                    skipped += 1
                    continue

                events = item.get("events", {}) or {}
                labeled = item.get("labeledEvents", {}) or {}
                shot = item.get("shot", {}) or {}

                offense_scheme = None
                for o in labeled.get("offenses") or []:
                    offense_scheme = _OFFENSE_MAP.get(o.lower(), o)
                    break
                defense_scheme = None
                for d in labeled.get("defenses") or []:
                    defense_scheme = _DEFENSE_MAP.get(d.lower(), d)
                    break

                shot_type = shot_action = direction = None
                contested = None
                for attr in shot.get("attributes") or []:
                    if attr in _SHOT_TYPE_MAP:
                        shot_type = _SHOT_TYPE_MAP[attr]
                    elif attr in _DIRECTION_MAP:
                        direction = _DIRECTION_MAP[attr]
                    elif attr in ("CAS", "OTD"):
                        shot_action = attr
                    elif attr == "GUARDED":
                        contested = True
                    elif attr == "UNGUARDED":
                        contested = False

                inner_actions = item.get("possessions") or []
                shot_clock_end = None
                for a in inner_actions:
                    if a.get("possessionType") in ("FGA", "FG", "FT", "FTA"):
                        shot_clock_end = _clean_shot_clock(a.get("shotClock"))
                if shot_clock_end is None and inner_actions:
                    shot_clock_end = _clean_shot_clock(inner_actions[-1].get("shotClock"))

                poss = models.Possession(
                    game_id=game.id,
                    quarter=quarter,
                    start_time=start_time,
                    end_time=end_time,
                    shot_clock_end=shot_clock_end,
                    video_time_start=labeled.get("videoTimeMark"),
                    shot_type=shot_type,
                    shot_action=shot_action,
                    contested=contested,
                    direction=direction,
                    passes=events.get("passes"),
                    reversals=events.get("ballReversals"),
                    paint_touch=events.get("paintTouch"),
                    offense_scheme=offense_scheme,
                    defense_scheme=defense_scheme,
                    offense_on_court=_format_players(item.get("lineupPlayers"), player_lookup),
                    defense_on_court=_format_players(item.get("opponentLineupPlayers"), player_lookup),
                    created_by=current_user.username,
                )

                for i, a in enumerate(inner_actions):
                    pt = a.get("possessionType")
                    info = player_lookup.get(str(a.get("playerId")), {})
                    team_name = team_name_for(a.get("teamId")) if a.get("teamId") is not None else "Unknown"
                    player_number = info.get("jersey")

                    if pt in ("FGA", "FG"):
                        action = "3PT" if a.get("is3Point") else "2PT"
                        result = "Miss" if pt == "FGA" else "Make"
                    else:
                        # Fall back to a placeholder rather than None — the
                        # column is required, and a missing/unknown vendor
                        # code shouldn't be able to sink the whole possession.
                        action = pt or "UNKNOWN"
                        result = _RESULT_BY_ACTION.get(pt)

                    poss.actions.append(models.PossessionAction(
                        sort_order=i, team=team_name, player_number=player_number,
                        action=action, result=result,
                    ))

                db.add(poss)
                db.flush()  # surface any constraint violation now, inside this savepoint
                created += 1
        except Exception as e:
            failed.append({
                "index": idx,
                "period": item.get("period"),
                "start": item.get("startGameClock"),
                "end": item.get("endGameClock"),
                "error": str(e),
            })

    db.commit()
    db.refresh(game)
    return {
        "game": schemas.GameOut.model_validate(game).model_dump(mode="json"),
        "possessions_created": created,
        "possessions_skipped": skipped,
        "possessions_failed": len(failed),
        "errors": failed[:20],  # capped so a badly-formed file can't blow up the response
    }


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
    data = payload.model_dump()
    game_uid = (data.pop("game_uid", None) or "").strip() or str(uuid.uuid4())
    game = models.Game(game_uid=game_uid, **data, created_by=current_user.username)
    db.add(game)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="That Game ID is already in use — choose a different one.",
        )
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
        d["actions"] = [
            {"team": a.team, "player_number": a.player_number, "action": a.action, "result": a.result}
            for a in p.actions
        ]
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
