# Privacy Policy (Local-First)

- The application stores user accounts, uploaded PDFs, generated questions, attempts, analytics, and tutor history in local files and SQLite by default.
- No API keys are ever sent to the frontend. AI keys remain backend-only.
- In `demo` mode, deterministic generation and marking run locally with no cloud AI calls.
- In `openai` mode, selected text chunks and prompts are sent to the configured provider.
- Users can delete their own books and associated processing data through the app. Full deletion guidance is in `README.md`.
