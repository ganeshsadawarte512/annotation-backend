from typing import Optional
import json as json_lib
import re
from datetime import datetime

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
    core_fields = {"date", "priority", "home_team", "home_team_id", "visitor_team", "visitor_team_id", "mf"}
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
        d["events"] = [
            {
                "id": ev.id, "team": ev.team, "player_number": ev.player_number,
                "action": ev.action, "result": ev.result,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            }
            for ev in p.events
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


@router.post("/import-json")
def import_game_json(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """One-shot import used by the dashboard's "Import JSON" button: takes
    a raw ShotTracker export (a JSON array of possession records, each
    carrying the game's own gameId/teamId/opponentTeamId/startTimestamp),
    finds or creates the matching Game row, then imports every possession
    into it using the same parser as /{game_id}/import-possessions.

    Team names aren't present in this export format (only numeric
    teamId/opponentTeamId), so a newly-created game gets placeholder
    names like "Team 4571" — rename it from the dashboard afterward.
    Re-importing the same file reuses the same game (matched by its
    ShotTracker gameId, stored in game_uid) rather than creating a
    duplicate game, but does not deduplicate individual possessions —
    importing the same file twice into the same game adds them twice.
    """
    raw_bytes = file.file.read()
    try:
        raw = json_lib.loads(raw_bytes)
    except (json_lib.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="That file isn't valid JSON.")

    if isinstance(raw, dict) and "possessions" in raw:
        items = raw["possessions"]
    elif isinstance(raw, list):
        items = raw
    else:
        raise HTTPException(
            status_code=400,
            detail="Expected a JSON array of possessions, or an object with a 'possessions' key.",
        )

    if not items or not isinstance(items[0], dict):
        raise HTTPException(status_code=400, detail="No possessions found in that file.")

    first = items[0]
    shot_uid = first.get("gameId")

    game = None
    if shot_uid:
        game = db.query(models.Game).filter(models.Game.game_uid == str(shot_uid)).first()

    if not game:
        start_ts = first.get("startTimestamp")
        if isinstance(start_ts, (int, float)):
            date_str = datetime.utcfromtimestamp(start_ts / 1000).strftime("%Y-%m-%d")
        else:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
        home_id = first.get("teamId")
        away_id = first.get("opponentTeamId")

        def resolve_team_name(team_id):
            """If this team ID was already imported before and someone renamed
            its placeholder to a real name, reuse that name instead of
            regenerating "Team {id}" again — otherwise every new game for the
            same real-world team gets a fresh placeholder, and your roster
            (which is looked up by team name) looks like it's been wiped."""
            if team_id is None:
                return None
            tid = str(team_id)
            placeholder = f"Team {tid}"
            for home_col, id_col in (
                (models.Game.home_team, models.Game.home_team_id),
                (models.Game.visitor_team, models.Game.visitor_team_id),
            ):
                hit = (
                    db.query(home_col)
                    .filter(id_col == tid, home_col != placeholder)
                    .order_by(models.Game.created_at.desc())
                    .first()
                )
                if hit and hit[0]:
                    return hit[0]
            return placeholder

        game = models.Game(
            date=date_str,
            home_team=resolve_team_name(home_id) if home_id is not None else "Home",
            home_team_id=str(home_id) if home_id is not None else None,
            visitor_team=resolve_team_name(away_id) if away_id is not None else "Away",
            visitor_team_id=str(away_id) if away_id is not None else None,
            created_by=current_user.username,
        )
        if shot_uid:
            game.game_uid = str(shot_uid)
        db.add(game)
        db.flush()  # get game.id before importing possessions into it

    is_shottracker_format = "startGameClock" in first and "possessions" in first
    if is_shottracker_format:
        created, failed, errors = _import_shottracker_format(db, game.id, items, current_user.username)
    else:
        created, failed, errors = _import_generic_format(db, game.id, items, current_user.username)

    db.commit()
    db.refresh(game)

    return {
        "game": schemas.GameOut.model_validate(game).model_dump(),
        "possessions_created": created,
        "possessions_skipped": 0,  # no possession-level dedup yet — see docstring
        "possessions_failed": failed,
        "errors": errors[:10],
    }


@router.post("/{game_id}/import-possessions")
def import_possessions(
    game_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),  # admin or annotator, same as adding one by hand
):
    """Bulk-loads possessions (and their individual events) from a JSON file.
    Two paths:
    1. ShotTracker-style export (each item has startGameClock/endGameClock/
       a nested 'possessions' event list) — parsed precisely, including real
       events (AST/STL/FG/etc.) mapped to our fixed action codes, and shot
       detail (type/action/contested/direction) pulled from the 'shot'
       object's attributes list.
    2. Anything else — falls back to a lenient field-name-alias matcher that
       fills safe defaults for whatever it can't recognize, so a partial
       file still imports something rather than failing outright.
    Team names are NOT guessed from teamId — that requires knowing which
    numeric ID is which of your two teams, which this file doesn't state.
    Raw teamId/playerId values are kept on each event so you can fill in
    real names while annotating, per your own workflow."""
    game = db.query(models.Game).get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    raw_bytes = file.file.read()
    try:
        raw = json_lib.loads(raw_bytes)
    except (json_lib.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="That file isn't valid JSON.")

    if isinstance(raw, dict) and "possessions" in raw:
        items = raw["possessions"]
    elif isinstance(raw, list):
        items = raw
    else:
        raise HTTPException(
            status_code=400,
            detail="Expected a JSON array of possessions, or an object with a 'possessions' key.",
        )

    is_shottracker_format = bool(items) and isinstance(items[0], dict) and (
        "startGameClock" in items[0] and "possessions" in items[0]
    )

    if is_shottracker_format:
        created, skipped, errors = _import_shottracker_format(db, game_id, items, current_user.username)
    else:
        created, skipped, errors = _import_generic_format(db, game_id, items, current_user.username)

    db.commit()
    return {"created": created, "skipped": skipped, "errors": errors[:10]}


# Event codes used by the real tracking data, mapped to the fixed action
# list you use for manual entry too.
_EVENT_ACTION_MAP = {
    "AST": "AST", "STL": "STL", "LBTO": "LBTO",
    "DEFENSIVE_REB": "DEFENSIVE_REB", "OFFENSIVE_REB": "OFFENSIVE_REB",
    "FLDN": "FLDN",
}
_SHOT_TYPE_MAP = {
    "JUMPSHOT": "Jumper", "LAYUP": "Layup", "DUNK": "Dunk",
    "HOOKSHOT": "Hook Shot", "FLOATER": "Floater",
}


def _quarter_from_period(period):
    if not period:
        return 1
    m = re.search(r"\d+", str(period))
    if m:
        return int(m.group())
    return 5 if "OT" in str(period).upper() else 1


def _import_shottracker_format(db, game_id, items, username):
    created, skipped, errors = 0, 0, []

    for i, item in enumerate(items):
        try:
            events_data = item.get("events") or {}
            labeled = item.get("labeledEvents") or {}
            shot = item.get("shot") or {}
            attrs = shot.get("attributes") or []

            def pick(*keys, source=labeled, fallback_source=events_data):
                for k in keys:
                    if k in source:
                        return source[k]
                for k in keys:
                    if k in fallback_source:
                        return fallback_source[k]
                return None

            offenses = labeled.get("offenses") or []
            defenses = labeled.get("defenses") or []
            deflected = labeled.get("passDeflectedBy") or []

            lineup = item.get("lineupPlayers") or []
            opp_lineup = item.get("opponentLineupPlayers") or []

            poss = models.Possession(
                game_id=game_id,
                quarter=_quarter_from_period(item.get("period")),
                clock=item.get("startGameClock") or "00:00",
                start_time=item.get("startGameClock"),
                end_time=item.get("endGameClock"),
                shot_clock_end=(str(item["endShotCock"]) if item.get("endShotCock") is not None else None),
                video_time_start=labeled.get("videoTimeMark"),
                shot_type=next((_SHOT_TYPE_MAP[a] for a in attrs if a in _SHOT_TYPE_MAP), None),
                shot_action="CAS" if "CAS" in attrs else ("OTD" if "OTD" in attrs else None),
                contested=True if "GUARDED" in attrs else (False if "UNGUARDED" in attrs else None),
                direction="Left" if "DIRECTIONLEFT" in attrs else ("Right" if "DIRECTIONRIGHT" in attrs else None),
                passes=pick("passes"),
                reversals=pick("ballReversals"),
                paint_touch=pick("paintTouch"),
                inbound_type=labeled.get("inbound"),
                offense_scheme=", ".join(offenses) if offenses else None,
                defense_scheme=", ".join(defenses) if defenses else None,
                deflected_pass_by=", ".join(str(x) for x in deflected) if deflected else None,
                # Real player names aren't in this export (only numeric IDs) — stored
                # as "#id" placeholders, same convention used for team names, so you
                # can swap in real names later without re-importing.
                offense_on_court=", ".join(f"#{p}" for p in lineup) if lineup else None,
                defense_on_court=", ".join(f"#{p}" for p in opp_lineup) if opp_lineup else None,
                created_by=username,
            )
            db.add(poss)
            db.flush()  # get poss.id before adding its events

            for ev in item.get("possessions", []):
                ptype = ev.get("possessionType")
                is3 = ev.get("is3Point", False)
                if ptype in ("FG", "FGA"):
                    action = "3PT" if is3 else "2PT"
                    result = "Make" if ptype == "FG" else "Miss"
                elif ptype in ("FT", "FTA"):
                    action = ptype
                    result = "Make" if ptype == "FT" else "Miss"
                elif ptype in _EVENT_ACTION_MAP:
                    action = _EVENT_ACTION_MAP[ptype]
                    result = None
                else:
                    continue  # unrecognized event code — skip just this sub-event, not the whole possession
                db.add(models.PossessionEvent(
                    possession_id=poss.id,
                    team=str(ev.get("teamId")) if ev.get("teamId") is not None else None,
                    player_number=str(ev.get("playerId")) if ev.get("playerId") is not None else None,
                    action=action,
                    result=result,
                    created_by=username,
                ))
            created += 1
        except Exception as e:
            skipped += 1
            errors.append({
                "period": item.get("period"),
                "start": item.get("startGameClock"),
                "end": item.get("endGameClock"),
                "error": str(e),
            })

    return created, skipped, errors


def _import_generic_format(db, game_id, items, username):
    # field_name -> our column name, matched after lowercasing and stripping spaces/underscores
    ALIASES = {
        "period": "quarter", "quarter": "quarter", "qtr": "quarter", "q": "quarter",
        "gcstart": "start_time", "start": "start_time", "starttime": "start_time", "start_time": "start_time",
        "gcend": "end_time", "end": "end_time", "endtime": "end_time", "end_time": "end_time",
        "shotclockend": "shot_clock_end", "shotclock": "shot_clock_end", "endshotcock": "shot_clock_end",
        "videotimestart": "video_time_start", "videotime": "video_time_start", "videotimemark": "video_time_start",
        "team": "team", "teamname": "team",
        "player": "player_number", "playernumber": "player_number", "playernum": "player_number", "number": "player_number",
        "action": "action", "play": "action", "event": "action",
        "result": "result", "outcome": "result",
        "shottype": "shot_type", "shotaction": "shot_action", "contested": "contested", "direction": "direction",
        "playtype": "play_type", "passes": "passes", "reversals": "reversals", "painttouch": "paint_touch",
        "inbound": "inbound_type", "inboundtype": "inbound_type",
        "offense": "offense_scheme", "offensescheme": "offense_scheme",
        "defense": "defense_scheme", "defensescheme": "defense_scheme",
        "offenseoncourt": "offense_on_court", "defenseoncourt": "defense_on_court",
        "deflectedpassby": "deflected_pass_by", "deflectedpass": "deflected_pass_by",
        "shotdefenders": "shot_defenders", "ballscreens": "ball_screens",
        "shotx": "shot_x", "shoty": "shot_y",
    }

    def normalize_key(k):
        return str(k).lower().replace(" ", "").replace("_", "").replace("-", "")

    def map_item(item):
        mapped = {}
        summary_text = None
        for k, v in item.items():
            norm = normalize_key(k)
            col = ALIASES.get(norm)
            if col:
                mapped[col] = v
            elif norm in ("summary", "description", "note", "notes", "text", "playbyplaydescription") and isinstance(v, str):
                summary_text = v

        if isinstance(mapped.get("ball_screens"), (list, dict)):
            mapped["ball_screens"] = json_lib.dumps(mapped["ball_screens"])

        quarter_raw = mapped.pop("quarter", None)
        try:
            mapped["quarter"] = int(quarter_raw) if quarter_raw not in (None, "") else 1
        except (TypeError, ValueError):
            mapped["quarter"] = _quarter_from_period(quarter_raw)

        mapped["clock"] = str(mapped.get("start_time") or mapped.get("clock") or "00:00")
        if not mapped.get("action"):
            mapped["action"] = summary_text or None

        for numeric_field in ("passes", "reversals"):
            if numeric_field in mapped:
                try:
                    mapped[numeric_field] = int(mapped[numeric_field])
                except (TypeError, ValueError):
                    mapped.pop(numeric_field)

        return mapped

    allowed_fields = set(schemas.PossessionCreate.model_fields.keys())
    created, skipped, errors = 0, 0, []

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            skipped += 1
            continue
        mapped = map_item(item)
        cleaned = {k: v for k, v in mapped.items() if k in allowed_fields}
        try:
            payload_obj = schemas.PossessionCreate(**cleaned)
        except Exception as e:
            skipped += 1
            errors.append({
                "period": item.get("period") or item.get("quarter") or item.get("Period"),
                "start": item.get("startGameClock") or item.get("GC Start") or item.get("start"),
                "end": item.get("endGameClock") or item.get("GC End") or item.get("end"),
                "error": str(e),
            })
            continue
        poss = models.Possession(game_id=game_id, **payload_obj.model_dump(), created_by=username)
        db.add(poss)
        created += 1

    return created, skipped, errors
