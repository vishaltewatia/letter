import secrets
from datetime import datetime, timedelta
from pathlib import Path
import re
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
import io
from app.core.config import get_settings
from app.core.deps import get_current_user
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.session import SessionLocal, get_db
from app.models.models import (
    Attempt,
    AttemptResponse,
    Book,
    Bookmark,
    Chapter,
    Chunk,
    Flashcard,
    PasswordResetToken,
    ProcessingJob,
    Question,
    Test,
    TestQuestion,
    TutorMessage,
    User,
    WrongAnswer,
)
from app.schemas.schemas import (
    AttemptStartInput,
    AutosaveInput,
    BookOut,
    BookRename,
    FlashcardInput,
    FlashcardOut,
    LoginInput,
    QuestionGenerateInput,
    QuestionOut,
    ResetConfirm,
    ResetRequest,
    SmartGenerateInput,
    SubmitInput,
    TestCreateInput,
    TestOut,
    Token,
    TutorInput,
    UserCreate,
    UserOut,
)
from app.services.ai_service import ai_provider
from app.services.pdf_service import chunk_text, detect_chapters, extract_pdf, extract_docx
from app.services.question_service import generate_demo_questions
from app.services.tutor_service import answer_from_chunks

router = APIRouter()
settings = get_settings()


def _book_owned(db: Session, user_id: int, book_id: int) -> Book:
    book = db.query(Book).filter(Book.id == book_id, Book.user_id == user_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


def _safe_filename(name: str) -> str:
    clean = Path(name or "uploaded.pdf").name
    clean = re.sub(r"[^A-Za-z0-9._ -]+", "_", clean).strip()
    # Don't auto-append .pdf if it's .docx
    if not clean.lower().endswith(".pdf") and not clean.lower().endswith(".docx"):
        clean += ".pdf"
    return clean[:120] or "uploaded.pdf"


def _create_processing_job(db: Session, book_id: int) -> ProcessingJob:
    active = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.book_id == book_id, ProcessingJob.status.in_(["Queued", "Processing"]))
        .order_by(ProcessingJob.id.desc())
        .first()
    )
    if active:
        return active
    job = ProcessingJob(book_id=book_id, status="Queued", message="Queued for processing")
    db.add(job)
    db.flush()
    return job


def _process_book(job_id: int, user_id: int, book_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        book = db.query(Book).filter(Book.id == book_id, Book.user_id == user_id).first()
        if not job or not book:
            return
        job.status = "Processing"
        book.status = "Processing"
        db.commit()

        book_path = Path(book.file_path)
        if book_path.name.lower().endswith(".docx"):
            pages = extract_docx(book_path)
        else:
            pages = extract_pdf(book_path)
        db.query(Chunk).filter(Chunk.book_id == book.id).delete(synchronize_session=False)
        db.query(Chapter).filter(Chapter.book_id == book.id).delete(synchronize_session=False)
        db.commit()

        chapters = detect_chapters(pages)
        chapter_map = {}
        for ch in chapters:
            chapter = Chapter(book_id=book.id, title=ch["title"], page_start=ch["page_start"])
            db.add(chapter)
            db.flush()
            chapter_map[ch["page_start"]] = chapter.id

        sorted_starts = sorted(chapter_map.keys())
        for page in pages:
            if not page["text"]:
                continue
            chapter_id = chapter_map[sorted_starts[0]] if sorted_starts else None
            for start in sorted_starts:
                if page["page"] >= start:
                    chapter_id = chapter_map[start]
            for piece in chunk_text(page["text"]):
                db.add(Chunk(book_id=book.id, chapter_id=chapter_id, page_number=page["page"], text=piece))

        book.status = "Ready"
        job.status = "Ready"
        job.message = f"Extracted {len(pages)} pages"
        db.commit()
    except Exception as exc:  # noqa: BLE001
        if job := db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first():
            job.status = "Failed"
            job.message = str(exc)
        if book := db.query(Book).filter(Book.id == book_id).first():
            book.status = "Failed"
            book.error_message = str(exc)
        db.commit()
    finally:
        db.close()


def _enqueue_or_run_processing(
    *,
    background_tasks: BackgroundTasks | None,
    job: ProcessingJob,
    user_id: int,
    book_id: int,
    run_sync: bool,
) -> None:
    if run_sync:
        _process_book(job.id, user_id, book_id)
        return
    if background_tasks is None:
        raise HTTPException(status_code=500, detail="Background task queue is unavailable")
    background_tasks.add_task(_process_book, job.id, user_id, book_id)


@router.post("/auth/signup", response_model=UserOut)
def signup(payload: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(func.lower(User.email) == payload.email.lower()).first():
        raise HTTPException(status_code=400, detail="Email already exists")
    user = User(email=payload.email.lower(), hashed_password=get_password_hash(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/auth/login", response_model=Token)
def login(payload: LoginInput, db: Session = Depends(get_db)):
    user = db.query(User).filter(func.lower(User.email) == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return Token(access_token=create_access_token(str(user.id)))


@router.get("/auth/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/auth/reset-request")
def reset_request(payload: ResetRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(func.lower(User.email) == payload.email.lower()).first()
    if not user:
        return {"message": "If the email exists, a reset token was created."}
    token = secrets.token_hex(16)
    db.add(PasswordResetToken(user_id=user.id, token=token))
    db.commit()
    return {
        "message": "Local-development reset token generated. In production, deliver via email.",
        "dev_reset_token": token,
    }


@router.post("/auth/reset-confirm")
def reset_confirm(payload: ResetConfirm, db: Session = Depends(get_db)):
    item = db.query(PasswordResetToken).filter(PasswordResetToken.token == payload.token, PasswordResetToken.used == False).first()  # noqa: E712
    if not item:
        raise HTTPException(status_code=400, detail="Invalid reset token")
    user = db.query(User).filter(User.id == item.user_id).first()
    user.hashed_password = get_password_hash(payload.new_password)
    item.used = True
    db.commit()
    return {"message": "Password updated"}


@router.post("/books/upload", response_model=BookOut)
async def upload_book(
    background_tasks: BackgroundTasks,
    sync: bool = Query(default=False),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    safe_name = _safe_filename(file.filename)
    is_pdf = safe_name.lower().endswith(".pdf")
    is_docx = safe_name.lower().endswith(".docx")

    if not (is_pdf or is_docx):
        raise HTTPException(status_code=400, detail="Only PDF or DOCX uploads are allowed")

    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File exceeds {settings.max_upload_mb}MB limit")

    if is_pdf and not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Invalid PDF signature")
    elif is_docx and not content.startswith(b"PK"): # DOCX are ZIP files
        raise HTTPException(status_code=400, detail="Invalid DOCX signature")

    user_dir = settings.storage_dir / "users" / str(current_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    file_path = user_dir / f"{int(datetime.utcnow().timestamp())}_{safe_name}"
    file_path.write_bytes(content)

    book = Book(user_id=current_user.id, title=safe_name, file_path=str(file_path), status="Uploading")
    db.add(book)
    db.commit()
    db.refresh(book)

    job = _create_processing_job(db, book.id)
    book.status = "Processing"
    db.commit()
    db.refresh(book)

    _enqueue_or_run_processing(
        background_tasks=background_tasks,
        job=job,
        user_id=current_user.id,
        book_id=book.id,
        run_sync=sync,
    )
    return book


@router.get("/books", response_model=list[BookOut])
def list_books(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Book).filter(Book.user_id == current_user.id).order_by(Book.created_at.desc()).all()


@router.patch("/books/{book_id}", response_model=BookOut)
def rename_book(book_id: int, payload: BookRename, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    book = _book_owned(db, current_user.id, book_id)
    book.title = payload.title
    db.commit()
    db.refresh(book)
    return book


@router.delete("/books/{book_id}")
def delete_book(book_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    book = _book_owned(db, current_user.id, book_id)
    Path(book.file_path).unlink(missing_ok=True)
    db.delete(book)
    db.commit()
    return {"message": "Book deleted"}


@router.post("/books/{book_id}/reprocess")
def reprocess_book(
    book_id: int,
    background_tasks: BackgroundTasks,
    sync: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    book = _book_owned(db, current_user.id, book_id)
    book.status = "Processing"
    job = _create_processing_job(db, book.id)
    db.commit()
    _enqueue_or_run_processing(
        background_tasks=background_tasks,
        job=job,
        user_id=current_user.id,
        book_id=book.id,
        run_sync=sync,
    )
    db.refresh(job)
    return {"job_id": job.id, "status": job.status}


@router.get("/books/{book_id}/processing-jobs")
def list_processing_jobs(book_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _book_owned(db, current_user.id, book_id)
    return (
        db.query(ProcessingJob)
        .filter(ProcessingJob.book_id == book_id)
        .order_by(ProcessingJob.id.desc())
        .all()
    )


@router.get("/processing-jobs/{job_id}")
def get_processing_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = (
        db.query(ProcessingJob)
        .join(Book, Book.id == ProcessingJob.book_id)
        .filter(ProcessingJob.id == job_id, Book.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return row


@router.post("/processing-jobs/{job_id}/retry")
def retry_processing_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    sync: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = (
        db.query(ProcessingJob)
        .join(Book, Book.id == ProcessingJob.book_id)
        .filter(ProcessingJob.id == job_id, Book.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Processing job not found")
    if row.status in {"Queued", "Processing"}:
        return {"job_id": row.id, "status": row.status}
    new_job = _create_processing_job(db, row.book_id)
    book = _book_owned(db, current_user.id, row.book_id)
    book.status = "Processing"
    db.commit()
    _enqueue_or_run_processing(
        background_tasks=background_tasks,
        job=new_job,
        user_id=current_user.id,
        book_id=row.book_id,
        run_sync=sync,
    )
    db.refresh(new_job)
    return {"job_id": new_job.id, "status": new_job.status}


@router.get("/books/{book_id}/chapters")
def chapters(book_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _book_owned(db, current_user.id, book_id)
    items = db.query(Chapter).filter(Chapter.book_id == book_id).order_by(Chapter.page_start.asc()).all()
    return items


@router.post("/questions/generate")
def generate_questions(payload: QuestionGenerateInput, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    book = _book_owned(db, current_user.id, payload.book_id)
    if book.status != "Ready":
        raise HTTPException(status_code=400, detail="Book processing is not ready")

    chunk_query = db.query(Chunk).filter(Chunk.book_id == book.id)
    if payload.chapter_id:
        chunk_query = chunk_query.filter(Chunk.chapter_id == payload.chapter_id)
    chunks = [
        {
            "text": c.text,
            "page_number": c.page_number,
            "chapter": db.query(Chapter).filter(Chapter.id == c.chapter_id).first().title if c.chapter_id else "General Content",
        }
        for c in chunk_query.limit(500).all()
    ]
    chapter_title = "General Content"
    if payload.chapter_id:
        chapter = db.query(Chapter).filter(Chapter.id == payload.chapter_id, Chapter.book_id == book.id).first()
        if not chapter:
            raise HTTPException(status_code=404, detail="Chapter not found")
        chapter_title = chapter.title

    generated = generate_demo_questions(chunks, chapter_title, payload.counts)
    created = 0
    for q in generated:
        exists = (
            db.query(Question)
            .filter(Question.user_id == current_user.id, Question.book_id == book.id, Question.question_text == q["question_text"])
            .first()
        )
        if exists:
            continue
        db.add(
            Question(
                user_id=current_user.id,
                book_id=book.id,
                chapter_id=payload.chapter_id,
                **q,
            )
        )
        created += 1
    db.commit()
    return {
        "created": created,
        "provider": ai_provider.mode(),
        "demo_mode": ai_provider.demo_enabled(),
        "mode_label": settings.demo_mode_label if ai_provider.demo_enabled() else "Live provider",
    }


@router.get("/questions", response_model=list[QuestionOut])
def list_questions(
    book_id: int,
    q_type: str | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _book_owned(db, current_user.id, book_id)
    query = db.query(Question).filter(Question.user_id == current_user.id, Question.book_id == book_id)
    if q_type:
        query = query.filter(Question.type == q_type)
    if search:
        query = query.filter(Question.question_text.ilike(f"%{search}%"))
    return query.offset((page - 1) * page_size).limit(page_size).all()


@router.delete("/questions/{question_id}")
def delete_question(question_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    question = db.query(Question).filter(Question.id == question_id, Question.user_id == current_user.id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    db.delete(question)
    db.commit()
    return {"message": "Question deleted"}


@router.post("/tests", response_model=TestOut)
def create_test(payload: TestCreateInput, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _book_owned(db, current_user.id, payload.book_id)
    questions = (
        db.query(Question)
        .filter(Question.user_id == current_user.id, Question.book_id == payload.book_id, Question.id.in_(payload.question_ids))
        .all()
    )
    if len(questions) != len(payload.question_ids):
        raise HTTPException(status_code=400, detail="Some questions are not available")
    total_marks = float(sum(q.marks for q in questions))
    test = Test(
        user_id=current_user.id,
        book_id=payload.book_id,
        title=payload.title,
        mode=payload.mode,
        duration_minutes=payload.duration_minutes,
        total_marks=total_marks,
    )
    db.add(test)
    db.flush()
    for q in questions:
        db.add(TestQuestion(test_id=test.id, question_id=q.id))
    db.commit()
    db.refresh(test)
    return test


@router.post("/tests/smart-generate", response_model=TestOut)
def smart_generate_test(payload: SmartGenerateInput, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _book_owned(db, current_user.id, payload.book_id)

    # Get all wrong answers for this book
    wrong_q_ids = [
        wa.question_id for wa in db.query(WrongAnswer).join(Question).filter(
            WrongAnswer.user_id == current_user.id, Question.book_id == payload.book_id
        ).all()
    ]

    selected_questions = []

    if not wrong_q_ids:
        # If no analytics data, fallback to picking recent questions
        selected_questions = db.query(Question).filter(
            Question.user_id == current_user.id,
            Question.book_id == payload.book_id
        ).order_by(Question.id.desc()).limit(payload.question_count).all()
    else:
        # Find weakest chapters (top 3 by wrong answer count)
        weakest = (
            db.query(Question.chapter_id, func.count(Question.id).label('wrong_count'))
            .filter(Question.id.in_(wrong_q_ids))
            .group_by(Question.chapter_id)
            .order_by(func.count(Question.id).desc())
            .limit(3)
            .all()
        )

        weakest_chapter_ids = [w[0] for w in weakest if w[0] is not None]

        if weakest_chapter_ids:
            # Pick available questions from the weakest chapters
            chapter_questions = db.query(Question).filter(
                Question.user_id == current_user.id,
                Question.book_id == payload.book_id,
                Question.chapter_id.in_(weakest_chapter_ids)
            ).order_by(func.random()).limit(payload.question_count).all()
            selected_questions.extend(chapter_questions)

        # Fill remaining slots with randomly selected general questions from the book
        if len(selected_questions) < payload.question_count:
            existing_ids = [q.id for q in selected_questions]
            fill_count = payload.question_count - len(selected_questions)
            fill_questions = db.query(Question).filter(
                Question.user_id == current_user.id,
                Question.book_id == payload.book_id,
                ~Question.id.in_(existing_ids)
            ).order_by(func.random()).limit(fill_count).all()
            selected_questions.extend(fill_questions)

    if not selected_questions:
        raise HTTPException(status_code=400, detail="Not enough questions available to generate a test")

    total_marks = float(sum(q.marks for q in selected_questions))
    test = Test(
        user_id=current_user.id,
        book_id=payload.book_id,
        title=payload.title,
        mode="practice",
        duration_minutes=payload.duration_minutes,
        total_marks=total_marks,
    )
    db.add(test)
    db.flush()
    for q in selected_questions:
        db.add(TestQuestion(test_id=test.id, question_id=q.id))
    db.commit()
    db.refresh(test)
    return test


@router.get("/tests", response_model=list[TestOut])
def list_tests(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Test).filter(Test.user_id == current_user.id).order_by(Test.created_at.desc()).all()


@router.get("/tests/{test_id}")
def get_test(test_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    test = db.query(Test).filter(Test.id == test_id, Test.user_id == current_user.id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    rows = (
        db.query(Question)
        .join(TestQuestion, TestQuestion.question_id == Question.id)
        .filter(TestQuestion.test_id == test_id)
        .all()
    )
    return {
        "id": test.id,
        "title": test.title,
        "mode": test.mode,
        "duration_minutes": test.duration_minutes,
        "total_marks": test.total_marks,
        "questions": [QuestionOut.model_validate(q).model_dump() for q in rows],
    }


@router.post("/attempts/start")
def start_attempt(payload: AttemptStartInput, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    test = db.query(Test).filter(Test.id == payload.test_id, Test.user_id == current_user.id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    existing = (
        db.query(Attempt)
        .filter(Attempt.test_id == test.id, Attempt.user_id == current_user.id, Attempt.status == "in_progress")
        .first()
    )
    if existing:
        return {"attempt_id": existing.id, "resumed": True}
    attempt = Attempt(test_id=test.id, user_id=current_user.id, max_score=test.total_marks)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return {"attempt_id": attempt.id, "resumed": False}


@router.get("/attempts")
def list_attempts(
    book_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Attempt, Test).join(Test, Test.id == Attempt.test_id).filter(Attempt.user_id == current_user.id)
    if book_id:
        query = query.filter(Test.book_id == book_id)
    rows = query.order_by(Attempt.id.desc()).all()
    return [
        {
            "attempt_id": attempt.id,
            "test_id": test.id,
            "test_title": test.title,
            "book_id": test.book_id,
            "status": attempt.status,
            "score": attempt.score,
            "max_score": attempt.max_score,
            "started_at": attempt.started_at,
            "submitted_at": attempt.submitted_at,
            "duration_minutes": test.duration_minutes,
        }
        for attempt, test in rows
    ]


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = (
        db.query(Attempt, Test)
        .join(Test, Test.id == Attempt.test_id)
        .filter(Attempt.id == attempt_id, Attempt.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Attempt not found")
    attempt, test = row
    responses = db.query(AttemptResponse).filter(AttemptResponse.attempt_id == attempt.id).all()
    response_map = {r.question_id: r for r in responses}
    questions = (
        db.query(Question)
        .join(TestQuestion, TestQuestion.question_id == Question.id)
        .filter(TestQuestion.test_id == test.id)
        .all()
    )
    return {
        "attempt_id": attempt.id,
        "test_id": test.id,
        "test_title": test.title,
        "book_id": test.book_id,
        "status": attempt.status,
        "score": attempt.score,
        "max_score": attempt.max_score,
        "mode": test.mode,
        "duration_minutes": test.duration_minutes,
        "started_at": attempt.started_at,
        "submitted_at": attempt.submitted_at,
        "questions": [
            {
                **QuestionOut.model_validate(q).model_dump(),
                "student_answer": response_map.get(q.id).answer_text if q.id in response_map else None,
                "obtained_marks": response_map.get(q.id).obtained_marks if q.id in response_map else None,
                "feedback": response_map.get(q.id).feedback if q.id in response_map else None,
            }
            for q in questions
        ],
    }


@router.get("/attempts/{attempt_id}/export")
def export_attempt_pdf(attempt_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    attempt_data = get_attempt(attempt_id, db, current_user)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)

    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    title_style.alignment = TA_CENTER
    h2 = styles['Heading2']
    h3 = styles['Heading3']
    normal = styles['Normal']

    story = []

    import html

    story.append(Paragraph(f"Exam Report: {html.escape(attempt_data['test_title'])}", title_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"<b>Score:</b> {attempt_data['score']} / {attempt_data['max_score']}", h2))
    story.append(Paragraph(f"<b>Date Submitted:</b> {attempt_data['submitted_at'].strftime('%Y-%m-%d %H:%M') if attempt_data.get('submitted_at') else 'N/A'}", normal))
    story.append(Spacer(1, 24))

    for i, q in enumerate(attempt_data['questions'], 1):
        question_block = []
        question_block.append(Paragraph(f"<b>Q{i} ({q['marks']} marks):</b> {html.escape(q['question_text'])}", h3))

        if q['options']:
            opts = ", ".join([f"{k}. {html.escape(v)}" for k, v in q['options'].items()])
            question_block.append(Paragraph(f"<b>Options:</b> {opts}", normal))

        ans = html.escape(q.get('student_answer') or "")
        question_block.append(Paragraph(f"<b>Your Answer:</b> {ans or '<i>No answer</i>'}", normal))

        if q.get('correct_answer'):
            question_block.append(Paragraph(f"<b>Correct Answer:</b> {html.escape(q['correct_answer'])}", normal))

        question_block.append(Paragraph(f"<b>Marks Obtained:</b> {q.get('obtained_marks')}", normal))

        if q.get('feedback'):
            question_block.append(Paragraph(f"<b>Feedback/Explanation:</b> {html.escape(q['feedback'])}", normal))

        question_block.append(Spacer(1, 12))
        story.append(KeepTogether(question_block))

    doc.build(story)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=exam_report_{attempt_id}.pdf"}
    )


@router.post("/attempts/{attempt_id}/autosave")
def autosave_attempt(attempt_id: int, payload: AutosaveInput, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    attempt = db.query(Attempt).filter(Attempt.id == attempt_id, Attempt.user_id == current_user.id, Attempt.status == "in_progress").first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found or already submitted")
    test_question_ids = {q.question_id for q in db.query(TestQuestion).filter(TestQuestion.test_id == attempt.test_id).all()}
    for question_id, answer in payload.answers.items():
        if int(question_id) not in test_question_ids:
            continue
        row = db.query(AttemptResponse).filter(AttemptResponse.attempt_id == attempt.id, AttemptResponse.question_id == int(question_id)).first()
        if row:
            row.answer_text = answer
        else:
            db.add(AttemptResponse(attempt_id=attempt.id, question_id=int(question_id), answer_text=answer))
    db.commit()
    return {"message": "Autosaved"}


@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(attempt_id: int, payload: SubmitInput, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    attempt = db.query(Attempt).filter(Attempt.id == attempt_id, Attempt.user_id == current_user.id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.status == "submitted":
        raise HTTPException(status_code=409, detail="Attempt already submitted")

    autosave_attempt(attempt_id, AutosaveInput(answers=payload.answers), db, current_user)
    responses = db.query(AttemptResponse).filter(AttemptResponse.attempt_id == attempt.id).all()
    q_by_id = {q.id: q for q in db.query(Question).filter(Question.id.in_([r.question_id for r in responses])).all()}

    total = 0.0
    wrong_inserted = 0
    for resp in responses:
        q = q_by_id.get(resp.question_id)
        if not q:
            continue
        if q.type == "mcq":
            if (resp.answer_text or "").strip().upper() == (q.correct_answer or "").strip().upper():
                resp.obtained_marks = q.marks
                resp.feedback = f"Correct. {q.explanation or ''}".strip()
            else:
                resp.obtained_marks = 0
                resp.feedback = f"Incorrect. Correct answer: {q.correct_answer}. {q.explanation or ''}".strip()
                if not db.query(WrongAnswer).filter(WrongAnswer.user_id == current_user.id, WrongAnswer.question_id == q.id, WrongAnswer.attempt_id == attempt.id).first():
                    db.add(WrongAnswer(user_id=current_user.id, question_id=q.id, attempt_id=attempt.id))
                    wrong_inserted += 1
        else:
            evaluation = ai_provider.evaluate_answer(q.question_text, q.model_answer or "", resp.answer_text or "", q.marks)
            txt = evaluation.content
            resp.feedback = (
                f"{txt} ({'Demo mode' if evaluation.demo_mode else 'Provider: '+evaluation.provider})"
            )
            # parse estimated mark from deterministic evaluator prefix
            try:
                mark_str = txt.split("Estimated-AI-Mark:")[1].split("/")[0].strip()
                resp.obtained_marks = max(0, min(q.marks, float(mark_str)))
            except Exception:  # noqa: BLE001
                resp.obtained_marks = q.marks * 0.5
        total += resp.obtained_marks

    attempt.status = "submitted"
    attempt.submitted_at = datetime.utcnow()
    attempt.score = round(total, 2)
    db.commit()

    return {
        "attempt_id": attempt.id,
        "score": attempt.score,
        "max_score": attempt.max_score,
        "wrong_answers_added": wrong_inserted,
        "estimated_ai_marking": ai_provider.demo_enabled() or ai_provider.mode() != "demo",
    }


@router.get("/analytics/dashboard")
def dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    total_books = db.query(Book).filter(Book.user_id == current_user.id).count()
    total_chapters = (
        db.query(Chapter)
        .join(Book, Book.id == Chapter.book_id)
        .filter(Book.user_id == current_user.id)
        .count()
    )
    total_questions = db.query(Question).filter(Question.user_id == current_user.id).count()
    tests_completed = db.query(Attempt).filter(Attempt.user_id == current_user.id, Attempt.status == "submitted").count()
    avg_score = (
        db.query(func.avg(Attempt.score / func.nullif(Attempt.max_score, 0) * 100))
        .filter(Attempt.user_id == current_user.id, Attempt.status == "submitted")
        .scalar()
        or 0
    )
    recent_attempts = (
        db.query(Attempt)
        .filter(Attempt.user_id == current_user.id, Attempt.status == "submitted")
        .order_by(Attempt.submitted_at.desc())
        .limit(5)
        .all()
    )
    attempts = (
        db.query(Attempt, Test)
        .join(Test, Test.id == Attempt.test_id)
        .filter(Attempt.user_id == current_user.id, Attempt.status == "submitted")
        .order_by(Attempt.submitted_at.desc())
        .all()
    )
    total_minutes = 0
    streak = 0
    completed_days = sorted(
        {
            a.submitted_at.date()
            for a, _ in attempts
            if a.submitted_at
        },
        reverse=True,
    )
    if completed_days:
        cursor = datetime.utcnow().date()
        for day in completed_days:
            if day == cursor:
                streak += 1
                cursor = cursor - timedelta(days=1)
            elif day < cursor:
                break
    for attempt, test in attempts:
        if attempt.submitted_at and attempt.started_at:
            elapsed = (attempt.submitted_at - attempt.started_at).total_seconds() / 60
            total_minutes += int(max(1, min(test.duration_minutes, elapsed)))
        else:
            total_minutes += max(1, test.duration_minutes)
    return {
        "books": total_books,
        "chapters": total_chapters,
        "questions": total_questions,
        "tests_completed": tests_completed,
        "average_score": round(float(avg_score), 2),
        "streak": streak,
        "study_time_minutes": total_minutes,
        "recent_activity": [
            {
                "attempt_id": a.id,
                "score": a.score,
                "max_score": a.max_score,
                "submitted_at": a.submitted_at,
            }
            for a in recent_attempts
        ],
        "next_recommendation": "Retry wrong answers and generate additional hard questions.",
        "insufficient_data": tests_completed < 2,
    }


@router.get("/revision/wrong-answers")
def wrong_answers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (
        db.query(Question)
        .join(WrongAnswer, WrongAnswer.question_id == Question.id)
        .filter(WrongAnswer.user_id == current_user.id)
        .all()
    )
    return [QuestionOut.model_validate(r).model_dump() for r in rows]


@router.post("/revision/bookmarks/{question_id}")
def bookmark(question_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Question).filter(Question.id == question_id, Question.user_id == current_user.id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    if not db.query(Bookmark).filter(Bookmark.user_id == current_user.id, Bookmark.question_id == question_id).first():
        db.add(Bookmark(user_id=current_user.id, question_id=question_id))
        db.commit()
    return {"message": "Bookmarked"}


@router.get("/revision/bookmarks")
def list_bookmarks(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (
        db.query(Question)
        .join(Bookmark, Bookmark.question_id == Question.id)
        .filter(Bookmark.user_id == current_user.id)
        .all()
    )
    return [QuestionOut.model_validate(r).model_dump() for r in rows]


@router.post("/flashcards", response_model=FlashcardOut)
def create_flashcard(payload: FlashcardInput, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _book_owned(db, current_user.id, payload.book_id)
    fc = Flashcard(user_id=current_user.id, book_id=payload.book_id, front=payload.front, back=payload.back)
    db.add(fc)
    db.commit()
    db.refresh(fc)
    return fc


@router.get("/flashcards", response_model=list[FlashcardOut])
def list_flashcards(book_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Flashcard).filter(Flashcard.user_id == current_user.id)
    if book_id:
        q = q.filter(Flashcard.book_id == book_id)
    return q.order_by(Flashcard.next_review_at.asc()).all()


@router.post("/tutor/chat")
def tutor_chat(payload: TutorInput, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _book_owned(db, current_user.id, payload.book_id)
    chunk_rows = db.query(Chunk).filter(Chunk.book_id == payload.book_id).limit(500).all()
    chunks = [
        {
            "text": c.text,
            "page_number": c.page_number,
            "chapter": db.query(Chapter).filter(Chapter.id == c.chapter_id).first().title if c.chapter_id else "General Content",
        }
        for c in chunk_rows
    ]
    answer, refs = answer_from_chunks(payload.question, chunks)
    db.add(TutorMessage(user_id=current_user.id, book_id=payload.book_id, role="user", content=payload.question))
    db.add(TutorMessage(user_id=current_user.id, book_id=payload.book_id, role="assistant", content=answer))
    db.commit()
    return {
        "answer": answer,
        "references": refs,
        "demo_mode": ai_provider.demo_enabled(),
        "source_notice": "Book-grounded retrieval only for selected book",
    }


@router.get("/tutor/history")
def tutor_history(book_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _book_owned(db, current_user.id, book_id)
    rows = (
        db.query(TutorMessage)
        .filter(TutorMessage.user_id == current_user.id, TutorMessage.book_id == book_id)
        .order_by(TutorMessage.created_at.asc())
        .all()
    )
    return [{"role": r.role, "content": r.content, "created_at": r.created_at} for r in rows]


@router.get("/system/mode")
def system_mode():
    return {
        "provider": ai_provider.mode(),
        "demo_mode": ai_provider.demo_enabled(),
        "label": settings.demo_mode_label if ai_provider.demo_enabled() else "Live AI provider",
    }
