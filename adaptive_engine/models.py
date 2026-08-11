"""
Core data models for the adaptive learning engine.
Plain dataclasses — no ORM dependency, works with any DB later.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


class ItemType(str, Enum):
    QUESTION = "question"
    LESSON = "lesson"


@dataclass
class Skill:
    id: str
    name: str
    subject: str
    prerequisite_ids: list[str] = field(default_factory=list)


@dataclass
class ContentItem:
    id: str
    skill_id: str
    item_type: ItemType
    difficulty: float
    payload: dict


@dataclass
class Student:
    id: str
    name: str
    ability: dict[str, float] = field(default_factory=dict)


@dataclass
class KnowledgeState:
    student_id: str
    skill_id: str
    p_mastery: float = 0.15
    last_seen: Optional[datetime] = None
    next_review_due: Optional[datetime] = None
    interval_days: float = 1.0
    ease: float = 2.5
    streak: int = 0


@dataclass
class Attempt:
    id: str
    student_id: str
    item_id: str
    skill_id: str
    correct: bool
    response_time_ms: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Highlight:
    id: str
    student_id: str
    item_id: str
    skill_id: str
    text: str
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class StudyDocument:
    id: str
    student_id: str
    filename: str
    chunks: list[str]
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BKTParams:
    skill_id: str
    p_init: float
    p_transit: float
    p_guess: float
    p_slip: float
    n_sequences: int
    fitted: bool
    trained_at: datetime = field(default_factory=datetime.utcnow)