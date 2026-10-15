import re
from pathlib import Path
from pypdf import PdfReader
from docx import Document


CHAPTER_RE = re.compile(r"^(chapter|unit|lesson)\s+\d+[:\-. ]?.*", re.IGNORECASE)


def extract_docx(path: Path) -> list[dict]:
    document = Document(str(path))
    pages: list[dict] = []

    # Docx doesn't have inherent page boundaries like PDF, so we'll approximate
    # pages by paragraphs or characters. Let's group paragraphs into "pages"
    # of roughly 2000 characters for consistency with chunking logic.
    current_page_text = []
    current_char_count = 0
    page_num = 1

    for para in document.paragraphs:
        text = para.text.strip()
        if text:
            current_page_text.append(text)
            current_char_count += len(text)

            if current_char_count > 2000:
                pages.append({"page": page_num, "text": "\n".join(current_page_text)})
                page_num += 1
                current_page_text = []
                current_char_count = 0

    if current_page_text:
        pages.append({"page": page_num, "text": "\n".join(current_page_text)})

    return pages

def extract_pdf(path: Path) -> list[dict]:
    reader = PdfReader(str(path))
    pages: list[dict] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        pages.append({"page": idx, "text": text})
    return pages


def detect_chapters(pages: list[dict]) -> list[dict]:
    chapters: list[dict] = []
    for page in pages:
        lines = [ln.strip() for ln in page["text"].splitlines() if ln.strip()]
        heading = next((ln for ln in lines[:8] if CHAPTER_RE.match(ln)), None)
        if heading:
            chapters.append({"title": heading[:255], "page_start": page["page"]})
    if not chapters:
        chapters = [{"title": "General Content", "page_start": 1}]
    return chapters


def chunk_text(page_text: str, max_chars: int = 1200) -> list[str]:
    clean = " ".join(page_text.split())
    if not clean:
        return []
    chunks = []
    while clean:
        chunk = clean[:max_chars]
        split = chunk.rfind(". ")
        if split > 200:
            chunk = chunk[: split + 1]
        chunks.append(chunk.strip())
        clean = clean[len(chunk):].strip()
    return chunks
