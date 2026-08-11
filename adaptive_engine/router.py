from collections import defaultdict
from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from . import engine
from .store import store
from .models import ItemType, Attempt as AttemptRecord, Highlight, StudyDocument, BKTParams, new_id
from .schemas import (
    NextItemResponse, AttemptRequest, AttemptResponse,
    ProgressResponse, ProgressEntry, TopicRequest, TopicResponse,
    QuizBatchResponse, QuizQuestionOut, QuizFeedbackRequest, QuizFeedbackResponse,
    HighlightCreate, HighlightOut, ChatRequest, ChatResponse,
    DocumentOut, DocumentUploadResponse, TopicFromDocumentRequest, BKTParamsOut,
)
from .generator import generate_topic_content, generate_topic_from_document, generate_quiz_feedback, chat_with_coach
from .rag import extract_text_from_pdf, chunk_text
from .bkt_trainer import fit_bkt

router = APIRouter(prefix="/adaptive", tags=["adaptive-learning"])


@router.get("/next/{student_id}", response_model=NextItemResponse)
async def get_next_item(student_id: str, subject: str | None = None):
    item = await engine.next_item(store, student_id, subject=subject)
    if item is None:
        raise HTTPException(status_code=204, detail="Nothing to serve — student is caught up.")
    skill = await store.get_skill(item.skill_id)
    state = await store.get_knowledge(student_id, item.skill_id)
    return NextItemResponse(
        item_id=item.id,
        skill_id=item.skill_id,
        skill_name=skill.name,
        item_type=item.item_type.value,
        difficulty=item.difficulty if item.item_type == ItemType.QUESTION else None,
        payload=item.payload,
        mastery=state.p_mastery,
    )


@router.post("/complete-lesson/{student_id}/{item_id}", response_model=AttemptResponse)
async def complete_lesson_endpoint(student_id: str, item_id: str):
    item = await store.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Unknown item_id")
    state = await engine.complete_lesson(store, student_id, item)
    return AttemptResponse(
        skill_id=item.skill_id,
        mastery=round(state.p_mastery, 3),
        mastered=state.p_mastery >= engine.MASTERY_THRESHOLD,
        next_review_due=state.next_review_due.isoformat() if state.next_review_due else None,
    )


@router.post("/attempt", response_model=AttemptResponse)
async def submit_attempt(attempt: AttemptRequest):
    item = await store.get_item(attempt.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Unknown item_id")

    state = await engine.record_attempt(store, attempt.student_id, item, attempt.correct)

    await store.log_attempt(AttemptRecord(
        id=new_id(), student_id=attempt.student_id, item_id=item.id,
        skill_id=item.skill_id, correct=attempt.correct,
        response_time_ms=attempt.response_time_ms,
    ))

    return AttemptResponse(
        skill_id=item.skill_id,
        mastery=round(state.p_mastery, 3),
        mastered=state.p_mastery >= engine.MASTERY_THRESHOLD,
        next_review_due=state.next_review_due.isoformat() if state.next_review_due else None,
    )


@router.get("/progress/{student_id}", response_model=ProgressResponse)
async def get_progress(student_id: str, subject: str | None = None):
    student = await store.get_or_create_student(student_id)
    skills = await store.all_skills(subject=subject)
    entries = []
    for skill in skills:
        state = await store.get_knowledge(student_id, skill.id)
        entries.append(ProgressEntry(
            skill_id=skill.id,
            skill_name=skill.name,
            mastery=round(state.p_mastery, 3),
            mastered=state.p_mastery >= engine.MASTERY_THRESHOLD,
            ability=student.ability.get(skill.id),
            next_review_due=state.next_review_due.isoformat() if state.next_review_due else None,
        ))
    return ProgressResponse(student_id=student_id, skills=entries)


@router.get("/subjects")
async def list_subjects():
    skills = await store.all_skills()
    return {"subjects": [{"skill_id": s.id, "name": s.name, "subject": s.subject} for s in skills]}


@router.post("/topics", response_model=TopicResponse)
async def create_topic(payload: TopicRequest):
    topic = payload.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")
    try:
        skill_id = await generate_topic_content(store, topic)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate content: {e}")
    return TopicResponse(skill_id=skill_id, subject=skill_id)


@router.get("/history/{student_id}")
async def get_history(student_id: str):
    docs = await store.get_mastery_history(student_id)
    grouped: dict[str, list] = defaultdict(list)
    for d in docs:
        grouped[d["skill_id"]].append({
            "timestamp": d["timestamp"].isoformat(),
            "mastery": round(d["p_mastery"], 3),
        })
    return {"student_id": student_id, "history": grouped}


@router.get("/quiz/{student_id}", response_model=QuizBatchResponse)
async def get_quiz(student_id: str, subject: str, level: str = "medium", count: int = 5):
    if level not in ("easy", "medium", "hard"):
        raise HTTPException(status_code=400, detail="level must be easy, medium, or hard")
    skill = await store.get_skill(subject)
    if skill is None:
        raise HTTPException(status_code=404, detail="Unknown subject")

    questions = await engine.get_quiz_batch(store, student_id, subject, level, count)
    return QuizBatchResponse(
        skill_id=subject,
        skill_name=skill.name,
        level=level,
        questions=[
            QuizQuestionOut(
                item_id=q.id,
                prompt=q.payload["prompt"],
                choices=q.payload["choices"],
                correct_index=q.payload["correct_index"],
                explanation=q.payload["explanation"],
                level=q.payload.get("level", level),
            )
            for q in questions
        ],
    )


@router.post("/quiz-feedback", response_model=QuizFeedbackResponse)
async def quiz_feedback(payload: QuizFeedbackRequest):
    skill = await store.get_skill(payload.subject)
    topic_name = skill.name if skill else payload.subject
    try:
        text = await generate_quiz_feedback(
            topic_name, payload.level, payload.score, payload.total, payload.missed
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Couldn't generate feedback: {e}")
    return QuizFeedbackResponse(feedback=text)


@router.post("/highlights", response_model=HighlightOut)
async def create_highlight(payload: HighlightCreate):
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    highlight = Highlight(
        id=new_id(), student_id=payload.student_id, item_id=payload.item_id,
        skill_id=payload.skill_id, text=text,
    )
    await store.add_highlight(highlight)
    return HighlightOut(
        id=highlight.id, item_id=highlight.item_id, skill_id=highlight.skill_id,
        text=highlight.text, created_at=highlight.created_at.isoformat(),
    )


@router.get("/highlights/{student_id}/{item_id}")
async def list_highlights(student_id: str, item_id: str):
    highlights = await store.get_highlights(student_id, item_id)
    return {
        "highlights": [
            HighlightOut(id=h.id, item_id=h.item_id, skill_id=h.skill_id, text=h.text, created_at=h.created_at.isoformat())
            for h in highlights
        ]
    }


@router.delete("/highlights/{highlight_id}")
async def remove_highlight(highlight_id: str, student_id: str):
    ok = await store.delete_highlight(highlight_id, student_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Highlight not found")
    return {"deleted": True}


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest):
    skills = await store.all_skills()
    summary_lines = []
    for skill in skills:
        state = await store.get_knowledge(payload.student_id, skill.id)
        if state.p_mastery > 0.16:
            tag = " (mastered)" if state.p_mastery >= engine.MASTERY_THRESHOLD else ""
            summary_lines.append(f"- {skill.name} ({skill.subject}): {round(state.p_mastery * 100)}% mastery{tag}")
    summary = "\n".join(summary_lines) if summary_lines else "No topics studied yet."

    try:
        reply = await chat_with_coach(summary, [m.dict() for m in payload.messages])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat failed: {e}")
    return ChatResponse(reply=reply)


# -------------------- RAG: document upload + grounded generation --------------------

@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(student_id: str = Form(...), file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported right now")

    file_bytes = await file.read()
    try:
        text = extract_text_from_pdf(file_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Couldn't read PDF: {e}")

    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="No readable text found in this PDF")

    doc = StudyDocument(id=new_id(), student_id=student_id, filename=file.filename, chunks=chunks)
    await store.save_document(doc)

    return DocumentUploadResponse(document_id=doc.id, filename=doc.filename, chunk_count=len(chunks))


@router.get("/documents/{student_id}")
async def get_documents(student_id: str):
    docs = await store.list_documents(student_id)
    return {
        "documents": [
            DocumentOut(id=d.id, filename=d.filename, chunk_count=len(d.chunks), created_at=d.created_at.isoformat())
            for d in docs
        ]
    }


@router.post("/topics/from-document", response_model=TopicResponse)
async def create_topic_from_document(payload: TopicFromDocumentRequest):
    topic = payload.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")
    document = await store.get_document(payload.document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        skill_id = await generate_topic_from_document(store, topic, document)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate content: {e}")
    return TopicResponse(skill_id=skill_id, subject=skill_id)


# -------------------- BKT parameter fitting (real ML) --------------------

@router.post("/train-bkt/{skill_id}", response_model=BKTParamsOut)
async def train_bkt(skill_id: str):
    skill = await store.get_skill(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Unknown skill")

    attempts = await store.get_attempts_for_skill(skill_id)
    fitted = fit_bkt(attempts)

    params = BKTParams(
        skill_id=skill_id, p_init=fitted["p_init"], p_transit=fitted["p_transit"],
        p_guess=fitted["p_guess"], p_slip=fitted["p_slip"],
        n_sequences=fitted["n_sequences"], fitted=fitted["fitted"],
    )
    await store.save_bkt_params(params)

    return BKTParamsOut(
        skill_id=params.skill_id, p_init=params.p_init, p_transit=params.p_transit,
        p_guess=params.p_guess, p_slip=params.p_slip, n_sequences=params.n_sequences,
        fitted=params.fitted, trained_at=params.trained_at.isoformat(),
    )


@router.get("/bkt-params/{skill_id}", response_model=BKTParamsOut)
async def get_bkt_params(skill_id: str):
    params = await store.get_bkt_params(skill_id)
    if params is None:
        raise HTTPException(status_code=404, detail="No trained parameters yet for this skill — call train-bkt first")
    return BKTParamsOut(
        skill_id=params.skill_id, p_init=params.p_init, p_transit=params.p_transit,
        p_guess=params.p_guess, p_slip=params.p_slip, n_sequences=params.n_sequences,
        fitted=params.fitted, trained_at=params.trained_at.isoformat(),
    )