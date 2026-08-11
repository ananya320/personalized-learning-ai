from pydantic import BaseModel
from typing import Optional


class NextItemResponse(BaseModel):
    item_id: str
    skill_id: str
    skill_name: str
    item_type: str
    difficulty: Optional[float] = None
    payload: dict
    mastery: float


class AttemptRequest(BaseModel):
    student_id: str
    item_id: str
    correct: bool
    response_time_ms: Optional[int] = None


class AttemptResponse(BaseModel):
    skill_id: str
    mastery: float
    mastered: bool
    next_review_due: Optional[str] = None


class ProgressEntry(BaseModel):
    skill_id: str
    skill_name: str
    mastery: float
    mastered: bool
    ability: Optional[float] = None
    next_review_due: Optional[str] = None


class ProgressResponse(BaseModel):
    student_id: str
    skills: list[ProgressEntry]


class TopicRequest(BaseModel):
    topic: str


class TopicResponse(BaseModel):
    skill_id: str
    subject: str


class QuizQuestionOut(BaseModel):
    item_id: str
    prompt: str
    choices: list[str]
    correct_index: int
    explanation: str
    level: str


class QuizBatchResponse(BaseModel):
    skill_id: str
    skill_name: str
    level: str
    questions: list[QuizQuestionOut]


class QuizFeedbackRequest(BaseModel):
    student_id: str
    subject: str
    level: str
    score: int
    total: int
    missed: list[dict] = []


class QuizFeedbackResponse(BaseModel):
    feedback: str


class HighlightCreate(BaseModel):
    student_id: str
    item_id: str
    skill_id: str
    text: str


class HighlightOut(BaseModel):
    id: str
    item_id: str
    skill_id: str
    text: str
    created_at: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    student_id: str
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    reply: str


class DocumentOut(BaseModel):
    id: str
    filename: str
    chunk_count: int
    created_at: str


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    chunk_count: int


class TopicFromDocumentRequest(BaseModel):
    student_id: str
    document_id: str
    topic: str


class BKTParamsOut(BaseModel):
    skill_id: str
    p_init: float
    p_transit: float
    p_guess: float
    p_slip: float
    n_sequences: int
    fitted: bool
    trained_at: str