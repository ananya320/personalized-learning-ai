"""
Generates lesson + leveled multiple-choice questions for any topic, using
Groq (free tier, Llama models). Also generates quiz feedback, powers the
AI Coach chat, and generates content GROUNDED in a student's uploaded
document via retrieval (RAG).
"""

import os
import json
from groq import Groq
from json_repair import repair_json
from .models import Skill, ContentItem, ItemType
from .rag import retrieve_relevant_chunks

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

LEVEL_DIFFICULTY = {"easy": 850, "medium": 1100, "hard": 1400}

GENERATION_PROMPT = """You are creating educational content for an adaptive learning app.

Topic: "{topic}"

Generate:
1. A standard lesson (3-5 sentences) explaining the core concept in plain, clear language for a general learner.
2. A "simple explanation" of the SAME concept, written as if for a curious 10-year-old — short sentences, an
   everyday analogy or comparison, no jargon at all.
3. One concrete real-world example showing the concept in action (2-3 sentences).
4. Exactly 15 multiple-choice questions about the topic: 5 "easy", 5 "medium", 5 "hard".
   Each question has exactly 4 choices, one correct answer, a "level" field
   (exactly "easy", "medium", or "hard"), and a 1-3 sentence explanation of
   why the correct answer is right (written for a student who got it wrong).

Respond with ONLY valid JSON, no markdown formatting, no commentary, matching exactly this shape:
{{
  "lesson_body": "string",
  "lesson_simple": "string",
  "lesson_example": "string",
  "questions": [
    {{
      "prompt": "string",
      "choices": ["string", "string", "string", "string"],
      "correct_index": 0,
      "explanation": "string",
      "level": "easy"
    }}
  ]
}}
"""

GROUNDED_GENERATION_PROMPT = """You are creating educational content for an adaptive learning app,
based STRICTLY on the following excerpts from the student's own uploaded material. Do not use
outside knowledge beyond what's needed to explain these excerpts clearly — everything you generate
must be traceable back to this material.

Topic the student wants to focus on: "{topic}"

Source material excerpts:
---
{context}
---

Generate:
1. A standard lesson (3-5 sentences) explaining the concept AS COVERED IN THE EXCERPTS ABOVE.
2. A "simple explanation" of the same concept — short sentences, an everyday analogy, no jargon.
3. One concrete example, drawn from or consistent with the source material.
4. Exactly 15 multiple-choice questions based on the excerpts: 5 "easy", 5 "medium", 5 "hard".
   Each has exactly 4 choices, one correct answer, a "level" field, and a 1-3 sentence explanation.

Respond with ONLY valid JSON, no markdown, no commentary, matching exactly this shape:
{{
  "lesson_body": "string",
  "lesson_simple": "string",
  "lesson_example": "string",
  "questions": [
    {{
      "prompt": "string",
      "choices": ["string", "string", "string", "string"],
      "correct_index": 0,
      "explanation": "string",
      "level": "easy"
    }}
  ]
}}
"""

FEEDBACK_PROMPT = """A student just finished a {level} quiz on "{topic}" and scored {score}/{total}.

Questions they got wrong:
{missed_list}

Write a short (2-4 sentence), warm, encouraging coaching note. If they missed
questions, briefly point at the general pattern in what tripped them up
without just repeating the explanations verbatim. If they got a perfect or
near-perfect score, congratulate them and suggest they try the next
difficulty level. Write directly to the student ("you"), plain text, no
markdown, no headers.
"""

COACH_SYSTEM_PROMPT = """You are a friendly, encouraging AI study coach inside a personalized learning app.

Here is the student's current performance summary across all topics they've studied:
{summary}

Use this to answer their questions about their progress, what to focus on next, and how to improve.
Be specific and reference actual topic names and mastery percentages from the summary when relevant.
Keep responses conversational and fairly short (3-6 sentences) unless they ask for more detail.
Never invent topics or numbers that aren't in the summary above — if you don't have data on something, say so."""


def _slugify(topic: str) -> str:
    return "-".join(topic.strip().lower().split())[:40]


def _parse_json_response(raw_text: str) -> dict:
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        # Groq occasionally emits near-valid JSON (unescaped quotes, trailing
        # commas). repair_json fixes common issues before we give up entirely.
        repaired = repair_json(raw_text)
        return json.loads(repaired)


async def _store_generated_content(store, skill_id: str, subject_name: str, subject: str, data: dict):
    skill = Skill(id=skill_id, name=subject_name, subject=subject)
    await store.add_skill(skill)

    lesson = ContentItem(
        id=f"{skill_id}-l1", skill_id=skill_id, item_type=ItemType.LESSON,
        difficulty=0,
        payload={
            "body": data["lesson_body"],
            "simple": data.get("lesson_simple", ""),
            "example": data.get("lesson_example", ""),
        },
    )
    await store.add_item(lesson)

    for idx, q in enumerate(data["questions"]):
        level = q.get("level", "medium")
        if level not in LEVEL_DIFFICULTY:
            level = "medium"
        item = ContentItem(
            id=f"{skill_id}-q{idx+1}", skill_id=skill_id, item_type=ItemType.QUESTION,
            difficulty=LEVEL_DIFFICULTY[level],
            payload={
                "prompt": q["prompt"],
                "choices": q["choices"],
                "correct_index": q["correct_index"],
                "explanation": q["explanation"],
                "level": level,
            },
        )
        await store.add_item(item)


async def generate_topic_content(store, topic: str) -> str:
    """General-knowledge generation — no source document."""
    skill_id = _slugify(topic)
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": GENERATION_PROMPT.format(topic=topic)}],
        temperature=0.7,
        max_tokens=4000,
        response_format={"type": "json_object"},
    )
    data = _parse_json_response(response.choices[0].message.content)
    await _store_generated_content(store, skill_id, topic.strip().title(), skill_id, data)
    return skill_id


async def generate_topic_from_document(store, topic: str, document) -> str:
    """RAG generation — grounded in the student's uploaded document.
    `document` is a StudyDocument with pre-chunked text."""
    relevant_chunks = retrieve_relevant_chunks(document.chunks, topic, top_k=4)
    context = "\n\n---\n\n".join(relevant_chunks)

    skill_id = _slugify(f"{topic}-{document.id[:6]}")
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": GROUNDED_GENERATION_PROMPT.format(topic=topic, context=context)}],
        temperature=0.5,
        max_tokens=4000,
        response_format={"type": "json_object"},
    )
    data = _parse_json_response(response.choices[0].message.content)
    display_name = f"{topic.strip().title()} (from {document.filename})"
    await _store_generated_content(store, skill_id, display_name, skill_id, data)
    return skill_id


async def generate_quiz_feedback(topic_name: str, level: str, score: int, total: int, missed: list[dict]) -> str:
    if missed:
        missed_list = "\n".join(f"- {m['prompt']} (explanation: {m['explanation']})" for m in missed)
    else:
        missed_list = "(none — perfect score)"

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{
            "role": "user",
            "content": FEEDBACK_PROMPT.format(
                topic=topic_name, level=level, score=score, total=total, missed_list=missed_list
            ),
        }],
        temperature=0.8,
        max_tokens=200,
    )
    return response.choices[0].message.content.strip()


async def chat_with_coach(summary: str, messages: list[dict]) -> str:
    chat_messages = [{"role": "system", "content": COACH_SYSTEM_PROMPT.format(summary=summary)}]
    chat_messages.extend(messages)

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=chat_messages,
        temperature=0.7,
        max_tokens=400,
    )
    return response.choices[0].message.content.strip()