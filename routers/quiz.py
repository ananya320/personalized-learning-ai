from fastapi import APIRouter, Body
from transformers import pipeline

router = APIRouter()
qg = pipeline("text2text-generation", model="valhalla/t5-small-qg-prepend")

@router.post("/")
async def generate_quiz(text: str = Body(..., embed=True)):
    result = qg(f"Generate 5 multiple-choice questions based on: {text}", max_length=300)
    return {"quiz": result[0]['generated_text']}
