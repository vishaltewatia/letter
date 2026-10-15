# Smart Study & Exam Preparation Platform (Local-First)

This repository now provides a locally runnable full-stack study platform:

- **Frontend:** React + TypeScript + Vite (localhost:5173)
- **Backend:** FastAPI + SQLAlchemy (localhost:8000)
- **Database:** SQLite (`backend/storage/app.db`)
- **File storage:** local filesystem (`backend/storage/users/...`)
- **AI mode:** deterministic **demo mode** by default, optional cloud/local provider configuration

> The original static HTML/CSS files are kept in the repository root, while the product app lives in `frontend/` and `backend/`.

## 1) Local-first architecture

- Local persistence across restarts (SQLite + local files)
- API keys are backend-only
- Provider abstraction:
  - `AI_PROVIDER=demo` (default deterministic mode)
  - `AI_PROVIDER=openai` (requires `OPENAI_API_KEY`)
  - `AI_PROVIDER=ollama` (optional local model endpoint)
- `/api/system/mode` explicitly reports demo/live mode label

## 2) Features implemented (working vertical slice)

- Auth: signup, login, local reset-token flow, JWT-protected endpoints
- User-scoped authorization checks for books, questions, tests, attempts, analytics, tutor history
- PDF upload + validation + persistent processing states (`Uploading`, `Processing`, `Ready`, `Failed`)
- PDF extraction + chunking + chapter detection + reprocess support
- Book-scoped deterministic question generation (MCQ/short/long) with source references and dedupe
- Question bank listing/filter/search/pagination + delete
- Custom test creation from selected questions, mixed question support, automatic total marks
- Exam attempts with autosave, refresh-safe persistence, submit guard against duplicates
- Marking:
  - MCQ auto-marking with explanation
  - Written answers rubric-like deterministic estimated-AI marking fallback
- Dashboard analytics from persisted records
- Wrong-answer notebook, bookmarks API, flashcards API, tutor with book-grounded retrieval

## 3) Prerequisites (Windows 11)

- Node.js 20+
- Python 3.11+
- npm

## 4) Quick start (Windows)

### Option A: one-click scripts

- CMD: run `start-dev.bat`
- PowerShell: run `./start-dev.ps1`

These scripts:
1. Create `backend/.venv`
2. Install backend deps
3. Start FastAPI on `http://localhost:8000`
4. Install frontend deps
5. Start Vite on `http://localhost:5173`

### Option B: manual

#### Backend

```bash
cd backend
python -m venv .venv
. .venv/Scripts/activate  # PowerShell: .venv/Scripts/Activate.ps1
pip install -r requirements.txt
python -m app.db.init_db
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Frontend

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

## 5) Environment variables

Copy from `.env.example`:

```bash
cp .env.example backend/.env
```

Key values:

- `SECRET_KEY`: required for JWT signing
- `DATABASE_URL`: default `sqlite:///./storage/app.db`
- `AI_PROVIDER`: `demo`, `openai`, `ollama`
- `OPENAI_API_KEY`: only needed for cloud mode
- `OLLAMA_BASE_URL`: optional for local model endpoint
- `VITE_API_BASE_URL`: frontend API base URL

## 6) Offline vs online behavior

### Works fully offline
- Auth
- PDF upload, extraction, chunking, chapter detection
- Deterministic question generation
- Test creation, autosave, marking, analytics, revision notebook, flashcards, tutor retrieval

### Requires internet
- Installing dependencies
- Cloud AI provider mode (`AI_PROVIDER=openai`)

## 7) Database setup, migrations, backup/restore

### Initialize

```bash
cd backend
python scripts/init_db.py
```

### Backup

```bash
cd backend
python scripts/backup_db.py
```

Creates timestamped backups in `backend/storage/backups/`.

### Restore

```bash
cd backend
python scripts/restore_db.py storage/backups/app_YYYYMMDD_HHMMSS.db
```

### Migrations

Current schema is auto-created on startup (`Base.metadata.create_all`).
For production evolution, wire Alembic migration scripts in `backend/` before changing schema on shared deployments.

## 8) Testing

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

Tests are designed to run in demo mode without paid AI credentials.

## 9) Data deletion guidance

- Delete a single book via API/UI (`DELETE /api/books/{book_id}`) to remove source file + linked data.
- Delete all local data by removing `backend/storage/`.
- For account-level deletion, remove user rows from DB and linked files under `backend/storage/users/<user_id>/`.

## 10) Security notes

- API keys are never exposed in frontend bundles.
- Passwords are hashed with bcrypt.
- JWT auth required for protected endpoints.
- User ownership checks are applied before returning/modifying private resources.
- Lightweight local rate-limiter enabled.

## 11) API overview

Main API groups under `/api`:

- `auth/*` (signup/login/reset/me)
- `books/*` (upload/list/rename/delete/reprocess/chapters)
- `questions/*` (generate/list/delete)
- `tests/*` and `attempts/*` (create/start/autosave/submit)
- `analytics/dashboard`
- `revision/*` (wrong answers/bookmarks)
- `flashcards/*`
- `tutor/*`
- `system/mode`

## 12) OCR and scanned PDFs

This baseline extracts text via `pypdf`. For scanned PDFs, integrate optional OCR (e.g., `ocrmypdf` + Tesseract) before calling the extraction pipeline; keep OCR optional so local setup remains simple.
