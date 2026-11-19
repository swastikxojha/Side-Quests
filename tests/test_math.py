import pytest


def reward(base_xp, rerolls):
    return max(5, base_xp // (2 ** rerolls))


def test_reroll_halves_xp_and_has_floor():
    assert [reward(100, n) for n in range(4)] == [100, 50, 25, 12]
    assert reward(10, 8) == 5


def test_progression_and_interest_quest_catalogue():
    from app.main import level_stats, quest_template
    assert level_stats(0)["level"] == 1
    assert level_stats(500)["level"] == 2
    assert level_stats(2000)["level"] == 3
    assert quest_template("Fitness", "daily", 0)[0] == "Take a 20-minute movement break"
    assert quest_template("Programming", "monthly", 0)[4] == "Hard"


@pytest.fixture
def api_client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app import main

    test_engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    test_sessions = sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(main, "engine", test_engine)
    monkeypatch.setattr(main, "SessionLocal", test_sessions)
    with TestClient(main.app) as client:
        yield client
    test_engine.dispose()


def test_auth_quest_completion_and_reroll_flow(api_client, caplog):
    from uuid import uuid4
    import re
    import logging
    from fastapi.testclient import TestClient
    from app.main import app

    email = f"{uuid4().hex}@example.com"
    client = api_client
    caplog.set_level(logging.INFO, logger="sidequests.auth")
    assert client.get("/api/quests").status_code == 401
    created = client.post("/api/auth/register", json={"username": "Tester", "email": email, "password": "Long-passphrase-123"})
    assert created.status_code == 201
    assert client.get("/ready").json()["status"] == "ready"
    assert client.get("/health").headers["x-frame-options"] == "DENY"
    assert client.get("/api/quests").json() == []
    assert client.patch("/api/profile", json={"timezone": "Asia/Kolkata", "username": "Quest Tester"}).status_code == 200
    assert client.get("/api/me").json()["timezone"] == "Asia/Kolkata"
    assert client.put("/api/interests", json={"interests": ["Programming", "Fitness", "Reading", "Photography"]}).status_code == 422
    assert client.put("/api/interests", json={"interests": ["Programming", "Fitness"]}).status_code == 200
    quests = client.get("/api/quests").json()
    assert len(client.get("/api/quest-templates").json()) >= 6
    assert len([q for q in quests if q["timeframe"] == "daily"]) == 3
    assert len([q for q in quests if q["timeframe"] == "weekly"]) == 2
    assert len([q for q in quests if q["timeframe"] == "monthly"]) == 1
    original = quests[0]
    assert original["due_at"] and original["estimated_minutes"] > 0
    rerolled = client.post(f"/api/quests/{original['id']}/reroll")
    assert rerolled.status_code == 200
    assert rerolled.json()["xp"] == original["xp"] // 2
    completed = client.post(f"/api/quests/{rerolled.json()['replacement_id']}/complete")
    assert completed.status_code == 200
    assert completed.json()["xp_earned"] > 0
    assert client.post(f"/api/quests/{rerolled.json()['replacement_id']}/complete").status_code == 409
    assert client.get("/api/progress/stats").status_code == 200
    assert client.post("/api/auth/forgot-password", json={"email": email}).status_code == 200
    reset_code = re.search(r"reset code for .*?: (\d{6})", caplog.text).group(1)
    assert client.post("/api/auth/reset-password", json={"email": email, "code": reset_code, "new_password": "New-passphrase-123"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": email, "password": "New-passphrase-123"}).status_code == 200
    for _ in range(9):
        assert client.post("/api/auth/login", json={"email": email, "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "wrong-password"}).status_code == 429
    other_email = f"{uuid4().hex}@example.com"
    with TestClient(app) as other_client:
        assert other_client.post("/api/auth/register", json={"username": "Other", "email": other_email, "password": "Long-passphrase-456"}).status_code == 201
        assert other_client.post(f"/api/quests/{original['id']}/complete").status_code == 404
