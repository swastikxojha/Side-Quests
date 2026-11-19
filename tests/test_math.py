def reward(base_xp, rerolls):
    return max(5, base_xp // (2 ** rerolls))


def test_reroll_halves_xp_and_has_floor():
    assert [reward(100, n) for n in range(4)] == [100, 50, 25, 12]
    assert reward(10, 8) == 5


def test_auth_quest_completion_and_reroll_flow():
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from app.main import app

    email = f"{uuid4().hex}@example.com"
    with TestClient(app) as client:
        created = client.post("/api/auth/register", json={"username": "Tester", "email": email, "password": "Long-passphrase-123"})
        assert created.status_code == 201
        assert client.patch("/api/profile", json={"timezone": "Asia/Kolkata", "username": "Quest Tester"}).status_code == 200
        assert client.get("/api/me").json()["timezone"] == "Asia/Kolkata"
        assert client.put("/api/interests", json={"interests": ["Programming", "Fitness", "Reading", "Photography"]}).status_code == 422
        assert client.put("/api/interests", json={"interests": ["Programming", "Fitness"]}).status_code == 200
        quests = client.get("/api/quests").json()
        assert len([q for q in quests if q["timeframe"] == "daily"]) == 3
        assert len([q for q in quests if q["timeframe"] == "weekly"]) == 2
        assert len([q for q in quests if q["timeframe"] == "monthly"]) == 1
        original = quests[0]
        rerolled = client.post(f"/api/quests/{original['id']}/reroll")
        assert rerolled.status_code == 200
        assert rerolled.json()["xp"] == original["xp"] // 2
        completed = client.post(f"/api/quests/{rerolled.json()['replacement_id']}/complete")
        assert completed.status_code == 200
        assert completed.json()["xp_earned"] > 0
        assert client.post(f"/api/quests/{rerolled.json()['replacement_id']}/complete").status_code == 409
        assert client.get("/api/progress/stats").status_code == 200
