"""
MongoDB-backed store for the adaptive engine — persistent and async, using
your existing `db` (Motor AsyncIOMotorDatabase) from app.db.

Collections used (created automatically on first write):
  adaptive_skills, adaptive_items, adaptive_students,
  adaptive_knowledge, adaptive_attempts, adaptive_seen_lessons,
  adaptive_mastery_history, adaptive_highlights, adaptive_documents,
  adaptive_bkt_params
"""

from typing import Optional

from app.db import db
from .models import (
    Skill, ContentItem, ItemType, Student, KnowledgeState, Attempt,
    Highlight, StudyDocument, BKTParams,
)


def _skill_to_doc(s: Skill) -> dict:
    return {"_id": s.id, "name": s.name, "subject": s.subject, "prerequisite_ids": s.prerequisite_ids}

def _doc_to_skill(d: dict) -> Skill:
    return Skill(id=d["_id"], name=d["name"], subject=d["subject"], prerequisite_ids=d.get("prerequisite_ids", []))


def _item_to_doc(i: ContentItem) -> dict:
    return {"_id": i.id, "skill_id": i.skill_id, "item_type": i.item_type.value, "difficulty": i.difficulty, "payload": i.payload}

def _doc_to_item(d: dict) -> ContentItem:
    return ContentItem(id=d["_id"], skill_id=d["skill_id"], item_type=ItemType(d["item_type"]), difficulty=d["difficulty"], payload=d.get("payload", {}))


def _state_to_doc(k: KnowledgeState) -> dict:
    return {
        "_id": f"{k.student_id}:{k.skill_id}",
        "student_id": k.student_id, "skill_id": k.skill_id, "p_mastery": k.p_mastery,
        "last_seen": k.last_seen, "next_review_due": k.next_review_due,
        "interval_days": k.interval_days, "ease": k.ease, "streak": k.streak,
    }

def _doc_to_state(d: dict) -> KnowledgeState:
    return KnowledgeState(
        student_id=d["student_id"], skill_id=d["skill_id"], p_mastery=d.get("p_mastery", 0.15),
        last_seen=d.get("last_seen"), next_review_due=d.get("next_review_due"),
        interval_days=d.get("interval_days", 1.0), ease=d.get("ease", 2.5), streak=d.get("streak", 0),
    )


class Store:
    def __init__(self, database=db):
        self.skills_col = database["adaptive_skills"]
        self.items_col = database["adaptive_items"]
        self.students_col = database["adaptive_students"]
        self.knowledge_col = database["adaptive_knowledge"]
        self.attempts_col = database["adaptive_attempts"]
        self.seen_lessons_col = database["adaptive_seen_lessons"]
        self.mastery_history_col = database["adaptive_mastery_history"]
        self.highlights_col = database["adaptive_highlights"]
        self.documents_col = database["adaptive_documents"]
        self.bkt_params_col = database["adaptive_bkt_params"]

    # -- skills / content --------------------------------------------------
    async def add_skill(self, skill: Skill):
        await self.skills_col.update_one({"_id": skill.id}, {"$set": _skill_to_doc(skill)}, upsert=True)

    async def get_skill(self, skill_id: str) -> Optional[Skill]:
        d = await self.skills_col.find_one({"_id": skill_id})
        return _doc_to_skill(d) if d else None

    async def all_skills(self, subject: Optional[str] = None) -> list[Skill]:
        query = {"subject": subject} if subject else {}
        docs = await self.skills_col.find(query).to_list(1000)
        return [_doc_to_skill(d) for d in docs]

    async def add_item(self, item: ContentItem):
        await self.items_col.update_one({"_id": item.id}, {"$set": _item_to_doc(item)}, upsert=True)

    async def get_item(self, item_id: str) -> Optional[ContentItem]:
        d = await self.items_col.find_one({"_id": item_id})
        return _doc_to_item(d) if d else None

    async def items_for_skill(self, skill_id: str) -> list[ContentItem]:
        docs = await self.items_col.find({"skill_id": skill_id}).to_list(1000)
        return [_doc_to_item(d) for d in docs]

    async def update_item_difficulty(self, item_id: str, difficulty: float):
        await self.items_col.update_one({"_id": item_id}, {"$set": {"difficulty": difficulty}})

    # -- students -------------------------------------------------------
    async def get_or_create_student(self, student_id: str, name: str = "") -> Student:
        d = await self.students_col.find_one({"_id": student_id})
        if d is None:
            student = Student(id=student_id, name=name or student_id)
            await self.students_col.insert_one({"_id": student_id, "name": student.name, "ability": {}})
            return student
        return Student(id=d["_id"], name=d.get("name", student_id), ability=d.get("ability", {}))

    async def set_ability(self, student_id: str, skill_id: str, ability: float):
        await self.students_col.update_one(
            {"_id": student_id}, {"$set": {f"ability.{skill_id}": ability}}, upsert=True
        )

    # -- knowledge state --------------------------------------------------
    async def get_knowledge(self, student_id: str, skill_id: str) -> KnowledgeState:
        d = await self.knowledge_col.find_one({"_id": f"{student_id}:{skill_id}"})
        if d is None:
            return KnowledgeState(student_id=student_id, skill_id=skill_id)
        return _doc_to_state(d)

    async def save_knowledge(self, state: KnowledgeState):
        await self.knowledge_col.update_one(
            {"_id": f"{state.student_id}:{state.skill_id}"}, {"$set": _state_to_doc(state)}, upsert=True
        )

    async def all_knowledge_for_student(self, student_id: str) -> list[KnowledgeState]:
        docs = await self.knowledge_col.find({"student_id": student_id}).to_list(1000)
        return [_doc_to_state(d) for d in docs]

    # -- attempts -----------------------------------------------------------
    async def log_attempt(self, attempt: Attempt):
        await self.attempts_col.insert_one({
            "_id": attempt.id, "student_id": attempt.student_id, "item_id": attempt.item_id,
            "skill_id": attempt.skill_id, "correct": attempt.correct,
            "response_time_ms": attempt.response_time_ms, "timestamp": attempt.timestamp,
        })

    async def get_attempted_item_ids(self, student_id: str, skill_id: str) -> set[str]:
        docs = await self.attempts_col.find(
            {"student_id": student_id, "skill_id": skill_id}
        ).to_list(1000)
        return {d["item_id"] for d in docs}

    async def get_attempts_for_skill(self, skill_id: str) -> list[dict]:
        """All attempts across all students for one skill — used for BKT fitting."""
        return await self.attempts_col.find({"skill_id": skill_id}).to_list(10000)

    # -- lesson exposure ----------------------------------------------------
    async def mark_lesson_seen(self, student_id: str, item_id: str):
        await self.seen_lessons_col.update_one(
            {"_id": f"{student_id}:{item_id}"}, {"$set": {"student_id": student_id, "item_id": item_id}}, upsert=True
        )

    async def lesson_seen(self, student_id: str, item_id: str) -> bool:
        d = await self.seen_lessons_col.find_one({"_id": f"{student_id}:{item_id}"})
        return d is not None

    # -- mastery history (for performance graphs) ---------------------------
    async def log_mastery_snapshot(self, student_id: str, skill_id: str, p_mastery: float, timestamp):
        await self.mastery_history_col.insert_one({
            "student_id": student_id, "skill_id": skill_id,
            "p_mastery": p_mastery, "timestamp": timestamp,
        })

    async def get_mastery_history(self, student_id: str) -> list[dict]:
        return await self.mastery_history_col.find({"student_id": student_id}).sort("timestamp", 1).to_list(5000)

    # -- highlights -----------------------------------------------------------
    async def add_highlight(self, h: Highlight):
        await self.highlights_col.insert_one({
            "_id": h.id, "student_id": h.student_id, "item_id": h.item_id,
            "skill_id": h.skill_id, "text": h.text, "created_at": h.created_at,
        })

    async def get_highlights(self, student_id: str, item_id: str) -> list[Highlight]:
        docs = await self.highlights_col.find(
            {"student_id": student_id, "item_id": item_id}
        ).sort("created_at", 1).to_list(200)
        return [
            Highlight(id=d["_id"], student_id=d["student_id"], item_id=d["item_id"],
                      skill_id=d["skill_id"], text=d["text"], created_at=d["created_at"])
            for d in docs
        ]

    async def delete_highlight(self, highlight_id: str, student_id: str) -> bool:
        result = await self.highlights_col.delete_one({"_id": highlight_id, "student_id": student_id})
        return result.deleted_count > 0

    # -- study documents (RAG source material) -------------------------------
    async def save_document(self, doc: StudyDocument):
        await self.documents_col.insert_one({
            "_id": doc.id, "student_id": doc.student_id, "filename": doc.filename,
            "chunks": doc.chunks, "created_at": doc.created_at,
        })

    async def get_document(self, document_id: str) -> Optional[StudyDocument]:
        d = await self.documents_col.find_one({"_id": document_id})
        if d is None:
            return None
        return StudyDocument(id=d["_id"], student_id=d["student_id"], filename=d["filename"],
                              chunks=d["chunks"], created_at=d["created_at"])

    async def list_documents(self, student_id: str) -> list[StudyDocument]:
        docs = await self.documents_col.find({"student_id": student_id}).sort("created_at", -1).to_list(100)
        return [
            StudyDocument(id=d["_id"], student_id=d["student_id"], filename=d["filename"],
                          chunks=d["chunks"], created_at=d["created_at"])
            for d in docs
        ]

    # -- BKT fitted parameters ------------------------------------------------
    async def save_bkt_params(self, params: BKTParams):
        await self.bkt_params_col.update_one(
            {"_id": params.skill_id},
            {"$set": {
                "skill_id": params.skill_id, "p_init": params.p_init, "p_transit": params.p_transit,
                "p_guess": params.p_guess, "p_slip": params.p_slip, "n_sequences": params.n_sequences,
                "fitted": params.fitted, "trained_at": params.trained_at,
            }},
            upsert=True,
        )

    async def get_bkt_params(self, skill_id: str) -> Optional[BKTParams]:
        d = await self.bkt_params_col.find_one({"_id": skill_id})
        if d is None:
            return None
        return BKTParams(skill_id=d["skill_id"], p_init=d["p_init"], p_transit=d["p_transit"],
                          p_guess=d["p_guess"], p_slip=d["p_slip"], n_sequences=d["n_sequences"],
                          fitted=d["fitted"], trained_at=d["trained_at"])


store = Store()