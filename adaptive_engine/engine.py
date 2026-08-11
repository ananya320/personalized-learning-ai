"""
Adaptive learning engine — async, MongoDB-backed via store.py.

Three techniques, combined:
1. Elo difficulty matching — question difficulty tracks student ability
2. Bayesian Knowledge Tracing — per-skill mastery estimate. Uses fitted
   per-skill parameters (from bkt_trainer.py's EM fit) when available,
   falling back to sane global defaults otherwise.
3. Spaced repetition — schedules review of mastered skills over time

next_item() avoids re-serving a question the student has already attempted,
as long as unattempted questions remain in that skill's pool.

get_quiz_batch() returns a randomized set of questions at a chosen difficulty
level (easy/medium/hard) for the leveled-quiz feature, also preferring
unattempted questions first.
"""

import math
import random
from datetime import datetime, timedelta

from .models import ContentItem, ItemType, KnowledgeState
from .store import Store

ELO_K = 32
MASTERY_THRESHOLD = 0.85
BKT_P_TRANSIT = 0.15
BKT_P_GUESS = 0.20
BKT_P_SLIP = 0.10
DEFAULT_ABILITY = 1000.0


# ---- 1. Elo difficulty matching --------------------------------------------

def expected_score(ability: float, difficulty: float) -> float:
    return 1.0 / (1.0 + math.pow(10, (difficulty - ability) / 400))


def update_elo(ability: float, difficulty: float, correct: bool) -> tuple[float, float]:
    expected = expected_score(ability, difficulty)
    actual = 1.0 if correct else 0.0
    new_ability = ability + ELO_K * (actual - expected)
    new_difficulty = difficulty - ELO_K * (actual - expected)
    return new_ability, new_difficulty


# ---- 2. Bayesian Knowledge Tracing ------------------------------------------

def update_mastery(p_mastery: float, correct: bool, p_guess: float = BKT_P_GUESS,
                    p_slip: float = BKT_P_SLIP, p_transit: float = BKT_P_TRANSIT) -> float:
    """Accepts optional per-skill fitted params (from bkt_trainer.py) instead
    of always using the global defaults — falls back to defaults if none given."""
    if correct:
        numerator = p_mastery * (1 - p_slip)
        denominator = numerator + (1 - p_mastery) * p_guess
    else:
        numerator = p_mastery * p_slip
        denominator = numerator + (1 - p_mastery) * (1 - p_guess)
    p_given_evidence = numerator / denominator if denominator > 0 else p_mastery
    p_next = p_given_evidence + (1 - p_given_evidence) * p_transit
    return min(max(p_next, 0.0), 0.999)


# ---- 3. Spaced repetition (SM-2-lite) ---------------------------------------

def schedule_review(state: KnowledgeState, correct: bool, now: datetime) -> KnowledgeState:
    if correct:
        state.streak += 1
        state.ease = max(1.3, state.ease + 0.1)
        state.interval_days = 1.0 if state.streak <= 1 else state.interval_days * state.ease
    else:
        state.streak = 0
        state.ease = max(1.3, state.ease - 0.2)
        state.interval_days = 1.0
    state.last_seen = now
    state.next_review_due = now + timedelta(days=state.interval_days)
    return state


# ---- recording attempts / lesson completion --------------------------------

async def record_attempt(store: Store, student_id: str, item: ContentItem, correct: bool, now: datetime | None = None) -> KnowledgeState:
    now = now or datetime.utcnow()
    student = await store.get_or_create_student(student_id)
    state = await store.get_knowledge(student_id, item.skill_id)

    if item.item_type == ItemType.QUESTION:
        ability = student.ability.get(item.skill_id, DEFAULT_ABILITY)
        new_ability, new_difficulty = update_elo(ability, item.difficulty, correct)
        await store.set_ability(student_id, item.skill_id, new_ability)
        await store.update_item_difficulty(item.id, new_difficulty)
        item.difficulty = new_difficulty

    # Use this skill's fitted BKT params if we've trained them, else defaults
    fitted = await store.get_bkt_params(item.skill_id)
    if fitted and fitted.fitted:
        state.p_mastery = update_mastery(state.p_mastery, correct, fitted.p_guess, fitted.p_slip, fitted.p_transit)
    else:
        state.p_mastery = update_mastery(state.p_mastery, correct)

    state = schedule_review(state, correct, now)
    await store.save_knowledge(state)
    await store.log_mastery_snapshot(student_id, item.skill_id, state.p_mastery, now)
    return state


async def complete_lesson(store: Store, student_id: str, item: ContentItem, now: datetime | None = None) -> KnowledgeState:
    now = now or datetime.utcnow()
    await store.mark_lesson_seen(student_id, item.id)
    state = await store.get_knowledge(student_id, item.skill_id)

    fitted = await store.get_bkt_params(item.skill_id)
    p_transit = fitted.p_transit if (fitted and fitted.fitted) else BKT_P_TRANSIT
    state.p_mastery = state.p_mastery + (1 - state.p_mastery) * p_transit

    state.last_seen = now
    await store.save_knowledge(state)
    await store.log_mastery_snapshot(student_id, item.skill_id, state.p_mastery, now)
    return state


# ---- next-item selection (single adaptive item) -----------------------------

async def _prereqs_met(store: Store, student_id: str, skill_id: str) -> bool:
    skill = await store.get_skill(skill_id)
    if not skill or not skill.prerequisite_ids:
        return True
    for pre_id in skill.prerequisite_ids:
        state = await store.get_knowledge(student_id, pre_id)
        if state.p_mastery < MASTERY_THRESHOLD:
            return False
    return True


async def next_item(store: Store, student_id: str, subject: str | None = None, now: datetime | None = None) -> ContentItem | None:
    now = now or datetime.utcnow()
    student = await store.get_or_create_student(student_id)
    candidate_skills = await store.all_skills(subject=subject)
    candidate_ids = {s.id for s in candidate_skills}

    all_knowledge = await store.all_knowledge_for_student(student_id)
    due = [k for k in all_knowledge if k.next_review_due and k.next_review_due <= now and k.skill_id in candidate_ids]

    if due:
        due.sort(key=lambda k: k.next_review_due)
        target_skill_id = due[0].skill_id
    else:
        unlocked_unmastered = []
        for s in candidate_skills:
            state = await store.get_knowledge(student_id, s.id)
            if state.p_mastery < MASTERY_THRESHOLD and await _prereqs_met(store, student_id, s.id):
                unlocked_unmastered.append(s)
        if not unlocked_unmastered:
            return None
        target_skill_id = unlocked_unmastered[0].id

    state = await store.get_knowledge(student_id, target_skill_id)
    items = await store.items_for_skill(target_skill_id)
    if not items:
        return None

    # very early in a skill -> show an unseen lesson first, if one exists
    if state.p_mastery < 0.3:
        lessons = []
        for i in items:
            if i.item_type == ItemType.LESSON and not await store.lesson_seen(student_id, i.id):
                lessons.append(i)
        if lessons:
            return lessons[0]

    questions = [i for i in items if i.item_type == ItemType.QUESTION]
    if not questions:
        return None
    ability = student.ability.get(target_skill_id, DEFAULT_ABILITY)

    # Prefer a question the student hasn't attempted yet, matched to their
    # ability. Only fall back to a previously-attempted question once the
    # whole pool for this skill is exhausted (that becomes a review, not a
    # same-question repeat).
    attempted_ids = await store.get_attempted_item_ids(student_id, target_skill_id)
    unattempted = [q for q in questions if q.id not in attempted_ids]
    pool = unattempted if unattempted else questions
    pool.sort(key=lambda q: abs(q.difficulty - ability))
    return pool[0]


# ---- quiz batch selection (leveled quiz feature) -----------------------------

async def get_quiz_batch(store: Store, student_id: str, skill_id: str, level: str, count: int = 5) -> list[ContentItem]:
    """Returns up to `count` questions at the given level for a skill, preferring
    ones the student hasn't attempted yet, in randomized order (a quiz batch,
    distinct from the single-item adaptive picker above)."""
    items = await store.items_for_skill(skill_id)
    questions = [i for i in items if i.item_type == ItemType.QUESTION and i.payload.get("level") == level]

    attempted_ids = await store.get_attempted_item_ids(student_id, skill_id)
    unattempted = [q for q in questions if q.id not in attempted_ids]

    pool = unattempted if len(unattempted) >= count else questions
    random.shuffle(pool)
    return pool[:count]