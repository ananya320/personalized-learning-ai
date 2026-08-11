from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# Updated subject list
subjects = ["AI", "DSA", "DBMS", "Machine learning"]

class Subject(BaseModel):
    name: str

@router.get("/", summary="Get all subjects")
def get_subjects():
    return {"subjects": subjects}

@router.post("/", summary="Add a new subject")
def add_subject(subject: Subject):
    if subject.name in subjects:
        raise HTTPException(status_code=400, detail="Subject already exists")
    subjects.append(subject.name)
    return {"message": f"Subject '{subject.name}' added successfully."}
