from io import BytesIO
from reportlab.pdfgen import canvas


def _pdf_bytes(text: str) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 800, text)
    c.showPage()
    c.save()
    return buf.getvalue()


def _auth_headers(client, email: str) -> dict:
    password = "password123"
    client.post("/api/auth/signup", json={"email": email, "password": password})
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    token = login.json()["access_token"]
    return {"Authorization": "Bearer " + token}


def test_end_to_end_demo_mode(client):
    headers = _auth_headers(client, "one@example.com")

    upload = client.post(
        "/api/books/upload",
        files={"file": ("biology.pdf", _pdf_bytes("Chapter 1 Cell structure and transport."), "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    book_id = upload.json()["id"]

    # processing runs via background task inside request lifecycle in tests
    books = client.get("/api/books", headers=headers).json()
    assert books[0]["status"] in {"Processing", "Ready"}

    # Ensure processing eventually ready by reprocess synchronous background test path
    client.post(f"/api/books/{book_id}/reprocess", headers=headers)
    books = client.get("/api/books", headers=headers).json()
    assert any(b["id"] == book_id for b in books)

    generated = client.post(
        "/api/questions/generate",
        json={"book_id": book_id, "counts": {"mcq": 4, "short": 2, "long": 1}},
        headers=headers,
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["demo_mode"] is True

    questions = client.get(f"/api/questions?book_id={book_id}&page_size=50", headers=headers)
    assert questions.status_code == 200
    question_rows = questions.json()
    assert len(question_rows) > 0

    test_payload = {
        "book_id": book_id,
        "title": "Demo mixed",
        "mode": "exam",
        "duration_minutes": 20,
        "question_ids": [q["id"] for q in question_rows[:5]],
    }
    created_test = client.post("/api/tests", json=test_payload, headers=headers)
    assert created_test.status_code == 200
    test_id = created_test.json()["id"]

    started = client.post("/api/attempts/start", json={"test_id": test_id}, headers=headers)
    assert started.status_code == 200
    attempt_id = started.json()["attempt_id"]

    detail = client.get(f"/api/tests/{test_id}", headers=headers).json()
    answers = {}
    for q in detail["questions"]:
        answers[q["id"]] = "A" if q["type"] == "mcq" else "Cells carry out vital functions."

    autosave = client.post(f"/api/attempts/{attempt_id}/autosave", json={"answers": answers}, headers=headers)
    assert autosave.status_code == 200

    submitted = client.post(f"/api/attempts/{attempt_id}/submit", json={"answers": answers}, headers=headers)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["max_score"] > 0

    dashboard = client.get("/api/analytics/dashboard", headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["tests_completed"] >= 1


def test_user_book_isolation(client):
    h1 = _auth_headers(client, "user1@example.com")
    h2 = _auth_headers(client, "user2@example.com")

    b1 = client.post(
        "/api/books/upload",
        files={"file": ("math.pdf", _pdf_bytes("Chapter 1 Algebraic equations."), "application/pdf")},
        headers=h1,
    ).json()

    forbidden = client.get(f"/api/questions?book_id={b1['id']}", headers=h2)
    assert forbidden.status_code in (404, 400)
