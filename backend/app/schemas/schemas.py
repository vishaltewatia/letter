from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class UserOut(BaseModel):
    id: int
    email: EmailStr

    model_config = {"from_attributes": True}


class LoginInput(BaseModel):
    email: EmailStr
    password: str


class ResetRequest(BaseModel):
    email: EmailStr


class ResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class BookOut(BaseModel):
    id: int
    title: str
    status: str
    error_message: str | None = None

    model_config = {"from_attributes": True}


class BookRename(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ChapterOut(BaseModel):
    id: int
    title: str
    page_start: int

    model_config = {"from_attributes": True}


class QuestionOut(BaseModel):
    id: int
    type: str
    question_text: str
    options: dict | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    model_answer: str | None = None
    keywords: list | None = None
    rubric: dict | None = None
    difficulty: str
    marks: float
    source_page: int | None = None
    source_chapter: str | None = None

    model_config = {"from_attributes": True}


class QuestionGenerateInput(BaseModel):
    book_id: int
    chapter_id: int | None = None
    counts: dict = Field(default_factory=lambda: {"mcq": 10, "short": 5, "long": 3})


class TestCreateInput(BaseModel):
    book_id: int
    title: str
    mode: str = "practice"
    duration_minutes: int = 30
    question_ids: list[int]


class SmartGenerateInput(BaseModel):
    book_id: int
    title: str = "Smart Review Test"
    duration_minutes: int = 20
    question_count: int = 10


class TestOut(BaseModel):
    id: int
    title: str
    mode: str
    duration_minutes: int
    total_marks: float

    model_config = {"from_attributes": True}


class AttemptStartInput(BaseModel):
    test_id: int


class AutosaveInput(BaseModel):
    answers: dict[int, str]


class SubmitInput(BaseModel):
    answers: dict[int, str]


class TutorInput(BaseModel):
    book_id: int
    question: str


class FlashcardInput(BaseModel):
    book_id: int
    front: str
    back: str


class FlashcardOut(BaseModel):
    id: int
    front: str
    back: str
    next_review_at: datetime

    model_config = {"from_attributes": True}
