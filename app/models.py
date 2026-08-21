import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, Text
from sqlalchemy.orm import relationship

from app.database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    annotator = "annotator"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.annotator, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    game_uid = Column(String, unique=True, index=True, default=lambda: str(uuid.uuid4()))
    date = Column(String, nullable=False)  # YYYY-MM-DD
    mf = Column(String(1), default="M")  # M or F
    home_team = Column(String, nullable=False)
    home_team_id = Column(String, nullable=True)
    visitor_team = Column(String, nullable=False)
    visitor_team_id = Column(String, nullable=True)
    video_path = Column(String, nullable=True)  # local path or S3 key
    video_status = Column(String, default="pending")  # pending, uploaded
    in_process = Column(Boolean, default=False)
    clock_vid_ok = Column(Boolean, default=False)
    complete_by = Column(String, nullable=True)
    qa_by = Column(String, nullable=True)
    is_complete = Column(Boolean, default=False)
    is_qa_done = Column(Boolean, default=False)
    has_video_error = Column(Boolean, default=False)
    has_annotation_error = Column(Boolean, default=False)
    notes = Column(Text, default="Received")
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    possessions = relationship("Possession", back_populates="game", cascade="all, delete-orphan")


class Player(Base):
    """A team's roster. Kept at the team-name level (not per-game) since the
    same team plays multiple games and shouldn't need re-entering each time."""
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    team_name = Column(String, nullable=False, index=True)
    jersey_number = Column(String, nullable=False)
    player_name = Column(String, nullable=False)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Possession(Base):
    __tablename__ = "possessions"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)

    # Basic play info (original fields)
    quarter = Column(Integer, nullable=False)
    clock = Column(String, nullable=False)  # mm:ss - kept for backward compatibility
    team = Column(String, nullable=False)
    player_number = Column(String, nullable=True)
    action = Column(String, nullable=False)
    result = Column(String, nullable=False)

    # Timing detail
    start_time = Column(String, nullable=True)       # game clock at possession start, e.g. "09:59:00"
    end_time = Column(String, nullable=True)          # game clock at possession end
    shot_clock_end = Column(String, nullable=True)    # shot clock value when the clip ends
    video_time_start = Column(String, nullable=True)  # timestamp into the video file itself

    # Shot detail
    shot_type = Column(String, nullable=True)     # e.g. "Layup", "Jumper", "Floater"
    shot_action = Column(String, nullable=True)   # e.g. "CAS", "OTD" (catch-and-shoot / off-the-dribble)
    contested = Column(Boolean, nullable=True)
    direction = Column(String, nullable=True)     # e.g. "Left", "Right"
    play_type = Column(String, nullable=True)     # e.g. "ISO Player", "PnR Ball Handler"
    shot_x = Column(String, nullable=True)         # court-diagram coordinates, stored as text (e.g. "0.62")
    shot_y = Column(String, nullable=True)

    # Possession-level detail
    passes = Column(Integer, nullable=True)
    reversals = Column(Integer, nullable=True)
    paint_touch = Column(Boolean, nullable=True)
    inbound_type = Column(String, nullable=True)   # e.g. "No Inbound"
    offense_scheme = Column(String, nullable=True)  # e.g. "Motion"
    defense_scheme = Column(String, nullable=True)  # e.g. "Man-to-Man"

    # On-court rosters — stored as comma-separated "#num Name" strings.
    # A dedicated roster table would be cleaner long-term; this is the
    # fast path to match the richer form without a bigger schema change.
    offense_on_court = Column(Text, nullable=True)
    defense_on_court = Column(Text, nullable=True)
    deflected_pass_by = Column(String, nullable=True)
    shot_defenders = Column(Text, nullable=True)

    # Ball screens — stored as JSON text: [{"screener": "...", "ball_handler": "..."}]
    ball_screens = Column(Text, nullable=True)

    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    game = relationship("Game", back_populates="possessions")
