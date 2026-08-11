from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from bson import ObjectId
from typing import Dict
from datetime import datetime

from app.db import db
from app.models import UserCreate, UserLogin, Token
from app.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user
)

# -------------------- Adaptive Engine --------------------
from adaptive_engine.router import router as adaptive_router
from adaptive_engine.seed_data import seed

app = FastAPI(title="Personalized Learning AI API")

# -------------------- CORS --------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Adaptive Engine router --------------------

app.include_router(adaptive_router)


@app.on_event("startup")
async def load_adaptive_content():
    """Loads sample skills/questions into the in-memory adaptive store so
    /adaptive/* endpoints work immediately. Replace seed() with a loader
    that pulls your real content from MongoDB once you're ready — see the
    README in adaptive_engine/ for how."""
    await seed()

# -------------------- Dummy AI Explanation --------------------

def generate_ai_explanation(question: str, correct_answer: str):
    """
    Dummy AI explanation system (No API required)
    """

    return {
        "explanation": f"The correct answer is '{correct_answer}' because it correctly solves the concept asked in the question.",
        "highlights": [
            correct_answer,
            "Core Concept",
            "Important Learning Point"
        ]
    }

# -------------------- Home --------------------

@app.get("/")
async def home():
    return {"message": "Welcome to Personalized Learning AI API 🚀"}

# -------------------- Signup --------------------

@app.post("/signup")
async def signup(user: UserCreate):

    existing_user = await db["users"].find_one({"email": user.email})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already exists"
        )

    await db["users"].insert_one({
        "email": user.email,
        "username": user.username,
        "password": hash_password(user.password),
        "created_at": datetime.utcnow()
    })

    return {"message": "User created successfully"}

# -------------------- Login --------------------

@app.post("/login", response_model=Token)
async def login(user: UserLogin):

    db_user = await db["users"].find_one({"email": user.email})

    if not db_user or not verify_password(user.password, db_user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    access_token = create_access_token({"sub": db_user["email"]})

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }

# -------------------- Get Quizzes --------------------

@app.get("/quizzes")
async def get_quizzes(current_user: str = Depends(get_current_user)):

    quizzes = await db["quizzes"].find().to_list(100)

    return [
        {
            "id": str(q["_id"]),
            "question": q["question"],
            "options": q["options"]
        }
        for q in quizzes
    ]

# -------------------- Submit Quiz --------------------

@app.post("/submit-quiz")
async def submit_quiz(
    answers: Dict[str, str],
    current_user: str = Depends(get_current_user)
):

    score = 0
    total = 0
    mistakes = []

    for qid, user_answer in answers.items():

        try:
            quiz = await db["quizzes"].find_one({"_id": ObjectId(qid)})
        except:
            continue

        if not quiz:
            continue

        total += 1

        if quiz["answer"] == user_answer:
            score += 1
        else:
            ai_feedback = generate_ai_explanation(
                quiz["question"],
                quiz["answer"]
            )

            mistakes.append({
                "question": quiz["question"],
                "your_answer": user_answer,
                "correct_answer": quiz["answer"],
                "ai_explanation": ai_feedback["explanation"],
                "highlights": ai_feedback["highlights"]
            })

    await db["results"].insert_one({
        "email": current_user,
        "score": score,
        "total": total,
        "submitted_at": datetime.utcnow()
    })

    return {
        "total_questions": total,
        "score": score,
        "mistakes": mistakes
    }

# -------------------- Summary --------------------

@app.get("/summary")
async def get_summary(current_user: str = Depends(get_current_user)):

    results = await db["results"].find(
        {"email": current_user}
    ).to_list(100)

    if not results:
        return {
            "attempts": 0,
            "average_score": 0,
            "history": []
        }

    total_score = sum(r["score"] for r in results)
    attempts = len(results)

    return {
        "attempts": attempts,
        "average_score": round(total_score / attempts, 2),
        "history": results
    }

# -------------------- Leaderboard --------------------

@app.get("/leaderboard")
async def leaderboard():

    pipeline = [
        {
            "$group": {
                "_id": "$email",
                "total_score": {"$sum": "$score"},
                "attempts": {"$sum": 1}
            }
        },
        {
            "$addFields": {
                "average_score": {
                    "$divide": ["$total_score", "$attempts"]
                }
            }
        },
        {
            "$sort": {"average_score": -1}
        }
    ]

    results = await db["results"].aggregate(pipeline).to_list(100)

    leaderboard = []
    rank = 1

    for r in results:
        user = await db["users"].find_one({"email": r["_id"]})

        leaderboard.append({
            "rank": rank,
            "username": user["username"] if user else "Unknown",
            "average_score": round(r["average_score"], 2),
            "attempts": r["attempts"]
        })

        rank += 1

    return leaderboard