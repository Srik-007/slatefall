from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class Choice(BaseModel):
    label: str
    text: str

class MCQ(BaseModel):
    question_id: str
    section_id: int
    question_text: str
    choices: list[Choice]
    correct_answer: str
    explanation: str
    topic_tag: str

class UserAnswer(BaseModel):
    question_id: str
    selected: str

class AnswerResult(BaseModel):
    question_id: str
    question_text: str
    selected: str
    correct_answer: str
    is_correct: bool
    explanation: str

class SessionResult(BaseModel):
    session_id: str
    section_ids: list[int]
    timestamp: str
    score: int
    total: int
    results: list[AnswerResult]

class PrepRequest(BaseModel):
    section_ids: list[int]
    simulate: bool=False

class KBSnapshot(BaseModel):
    snapshot_at: str
    sessions: list[dict]