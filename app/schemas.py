from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ---------- Auth ----------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: str


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "annotator"  # only an admin can create another admin


# ---------- Games ----------
class GameCreate(BaseModel):
    date: str
    mf: str = "M"
    home_team: str
    home_team_id: Optional[str] = None
    visitor_team: str
    visitor_team_id: Optional[str] = None


class GameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    game_uid: str
    date: str
    mf: str
    home_team: str
    visitor_team: str
    video_path: Optional[str]
    video_status: str
    in_process: bool
    clock_vid_ok: bool
    complete_by: Optional[str]
    qa_by: Optional[str]
    is_complete: bool
    is_qa_done: bool
    has_video_error: bool
    has_annotation_error: bool
    notes: Optional[str]
    created_at: datetime


class GameUpdate(BaseModel):
    """Partial update for dashboard checkboxes, notes, and (admin-only) core
    game info. Only send the fields you're changing — everything else is
    left as-is. When is_complete or is_qa_done is included, the backend
    auto-sets complete_by/qa_by to the current user's username (or clears
    it if unchecked) — the frontend never sends those two fields directly.
    date/home_team/visitor_team/mf/home_team_id/visitor_team_id are
    admin-only; the backend rejects them from an annotator."""
    in_process: Optional[bool] = None
    clock_vid_ok: Optional[bool] = None
    is_complete: Optional[bool] = None
    is_qa_done: Optional[bool] = None
    has_video_error: Optional[bool] = None
    has_annotation_error: Optional[bool] = None
    notes: Optional[str] = None
    date: Optional[str] = None
    home_team: Optional[str] = None
    home_team_id: Optional[str] = None
    visitor_team: Optional[str] = None
    visitor_team_id: Optional[str] = None
    mf: Optional[str] = None


# ---------- Players (team rosters) ----------
class PlayerCreate(BaseModel):
    team_name: str
    jersey_number: str
    player_name: str


class PlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    team_name: str
    jersey_number: str
    player_name: str


# ---------- Possessions ----------
class PossessionCreate(BaseModel):
    quarter: int
    clock: str
    team: str
    player_number: Optional[str] = None
    action: str
    result: str

    # Timing detail
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    shot_clock_end: Optional[str] = None
    video_time_start: Optional[str] = None

    # Shot detail
    shot_type: Optional[str] = None
    shot_action: Optional[str] = None
    contested: Optional[bool] = None
    direction: Optional[str] = None
    play_type: Optional[str] = None
    shot_x: Optional[str] = None
    shot_y: Optional[str] = None

    # Possession-level detail
    passes: Optional[int] = None
    reversals: Optional[int] = None
    paint_touch: Optional[bool] = None
    inbound_type: Optional[str] = None
    offense_scheme: Optional[str] = None
    defense_scheme: Optional[str] = None

    # Rosters (comma-separated "#num Name" strings) and screens (JSON text)
    offense_on_court: Optional[str] = None
    defense_on_court: Optional[str] = None
    deflected_pass_by: Optional[str] = None
    shot_defenders: Optional[str] = None
    ball_screens: Optional[str] = None


class PossessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    game_id: int
    quarter: int
    clock: str
    team: str
    player_number: Optional[str]
    action: str
    result: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    shot_clock_end: Optional[str] = None
    video_time_start: Optional[str] = None
    shot_type: Optional[str] = None
    shot_action: Optional[str] = None
    contested: Optional[bool] = None
    direction: Optional[str] = None
    play_type: Optional[str] = None
    shot_x: Optional[str] = None
    shot_y: Optional[str] = None
    passes: Optional[int] = None
    reversals: Optional[int] = None
    paint_touch: Optional[bool] = None
    inbound_type: Optional[str] = None
    offense_scheme: Optional[str] = None
    defense_scheme: Optional[str] = None
    offense_on_court: Optional[str] = None
    defense_on_court: Optional[str] = None
    deflected_pass_by: Optional[str] = None
    shot_defenders: Optional[str] = None
    ball_screens: Optional[str] = None
    created_by: Optional[str]
    created_at: datetime
