from fastapi import APIRouter, Body
from transformers import pipeline

router = APIRouter()
summarizer = pipeline("summarization", model="facebook/bart-large-cnn")

@router.post("/")
async def get_summary(text: str = Body(..., embed=True)):
    result = summarizer(text, max_length=150, min_length=50, do_sample=False)
    return {"summary": result[0]['summary_text']}
