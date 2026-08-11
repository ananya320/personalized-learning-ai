from fastapi import APIRouter
from database import progress_collection

router = APIRouter(prefix="/learning", tags=["Learning"])

@router.post("/update_progress")
async def update_progress(data: dict):
    email = data.get("email")
    topic = data.get("topic")
    score = data.get("score")

    if not email or not topic or score is None:
        return {"error": "Missing fields"}

    await progress_collection.update_one(
        {"email": email, "topic": topic},
        {"$set": {"score": score}},
        upsert=True
    )

    return {"message": "Progress updated successfully"}

@router.get("/get_progress/{email}")
async def get_progress(email: str):
    progress = await progress_collection.find({"email": email}).to_list(100)
    return {"progress": progress}