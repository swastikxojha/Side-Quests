import os
import logging
import smtplib
from contextlib import asynccontextmanager
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from pathlib import Path
from secrets import randbelow
from hashlib import sha256
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator
from pwdlib import PasswordHash
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

BASE = Path(__file__).parent
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sidequests.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(engine, expire_on_commit=False)
passwords = PasswordHash.recommended()


@asynccontextmanager
async def lifespan(_app):
    if os.getenv("APP_ENV", "development") == "production" and (not os.getenv("SECRET_KEY") or os.getenv("SECRET_KEY") == "dev-only-change-me"):
        raise RuntimeError("Set a strong SECRET_KEY before production startup")
    if os.getenv("APP_ENV", "development") != "production" and os.getenv("APP_AUTO_CREATE_SCHEMA", "true").lower() == "true":
        Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed_quest_templates(session)
    yield


app = FastAPI(title="Side Quests", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
logger = logging.getLogger("sidequests.auth")


class Base(DeclarativeBase): pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    xp: Mapped[int] = mapped_column(Integer, default=0)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")


class QuestTemplate(Base):
    __tablename__ = "quest_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(String(500))
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    category: Mapped[str] = mapped_column(String(40))
    estimated_minutes: Mapped[int] = mapped_column(Integer)
    difficulty: Mapped[str] = mapped_column(String(20))
    base_xp: Mapped[int] = mapped_column(Integer)


class Quest(Base):
    __tablename__ = "user_quests"
    __table_args__ = (UniqueConstraint("user_id", "timeframe", "period_key", "slot", "generation", name="uq_user_quest_period_slot"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("quest_templates.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(String(500))
    timeframe: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(40), default="Personal growth")
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=20)
    period_key: Mapped[str] = mapped_column(String(20), default="")
    slot: Mapped[int] = mapped_column(Integer, default=0)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    difficulty: Mapped[str] = mapped_column(String(20), default="Medium")
    base_xp: Mapped[int] = mapped_column(Integer, default=50)
    rerolls: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResetCode(Base):
    __tablename__ = "reset_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class UserInterest(Base):
    __tablename__ = "user_interests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))


class XpLedger(Base):
    __tablename__ = "xp_ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    quest_id: Mapped[int | None] = mapped_column(ForeignKey("user_quests.id", ondelete="SET NULL"), unique=True, nullable=True)
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Achievement(Base):
    __tablename__ = "achievements"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(200))


class UserAchievement(Base):
    __tablename__ = "user_achievements"
    __table_args__ = (UniqueConstraint("user_id", "achievement_id", name="uq_user_achievement"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    achievement_id: Mapped[int] = mapped_column(ForeignKey("achievements.id", ondelete="CASCADE"))
    unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RateLimit(Base):
    __tablename__ = "rate_limits"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)


def db_session():
    with SessionLocal() as session:
        yield session


class AuthInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class Signup(AuthInput):
    username: str = Field(min_length=2, max_length=40)


class InterestInput(BaseModel):
    interests: list[str]

    @field_validator("interests")
    @classmethod
    def valid_interests(cls, values):
        values = list(dict.fromkeys(v.strip() for v in values if v.strip()))
        if not 1 <= len(values) <= 3:
            raise ValueError("Choose between one and three interests")
        return values


class ForgotInput(BaseModel):
    email: EmailStr


class ResetInput(BaseModel):
    email: EmailStr
    code: str
    new_password: str = Field(min_length=8, max_length=128)


class ProfileInput(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=40)
    timezone: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


def rate_limit(session: Session, request: Request, action: str, limit: int, seconds: int = 900):
    now = datetime.now(timezone.utc)
    ip = request.client.host if request.client else "unknown"
    key = f"{action}:{ip}"
    record = session.get(RateLimit, key)
    if record:
        start = record.window_start if record.window_start.tzinfo else record.window_start.replace(tzinfo=timezone.utc)
        if now - start >= timedelta(seconds=seconds): record.window_start, record.attempts = now, 1
        else:
            record.attempts += 1
            if record.attempts > limit:
                session.commit()
                raise HTTPException(429, "Too many attempts. Please try again later.", headers={"Retry-After": str(seconds)})
    else: session.add(RateLimit(key=key, window_start=now, attempts=1))
    session.commit()


@app.get("/")
def home(): return FileResponse(BASE / "static" / "index.html")


@app.get("/health")
def health(): return {"status": "ok"}


@app.get("/ready")
def ready(session: Session = Depends(db_session)):
    try: session.execute(select(1))
    except Exception: raise HTTPException(503, "Database is unavailable")
    return {"status": "ready"}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def get_user(request, session: Session) -> User:
    from hmac import new, compare_digest
    token = request.cookies.get("sq_session", "")
    try:
        uid, expires, sig = token.split(".", 2)
        signed = f"{uid}.{expires}"
        expected = new(os.getenv("SECRET_KEY", "dev-only-change-me").encode(), signed.encode(), "sha256").hexdigest()
        if not compare_digest(sig, expected): raise ValueError()
        if int(expires) < int(datetime.now(timezone.utc).timestamp()): raise ValueError()
        user = session.get(User, int(uid))
        if user: return user
    except Exception: pass
    raise HTTPException(401, "Please sign in")


def issue_cookie(response: Response, user: User):
    from hmac import new
    uid = str(user.id)
    expires = str(int(datetime.now(timezone.utc).timestamp()) + 60 * 60 * 24 * 7)
    signed = f"{uid}.{expires}"
    sig = new(os.getenv("SECRET_KEY", "dev-only-change-me").encode(), signed.encode(), "sha256").hexdigest()
    response.set_cookie("sq_session", f"{signed}.{sig}", httponly=True, samesite="lax", secure=os.getenv("COOKIE_SECURE", "false").lower() == "true", max_age=60 * 60 * 24 * 7)


def level_stats(total_xp: int):
    level = 1
    while total_xp >= 500 * level * level: level += 1
    lower = 500 * (level - 1) ** 2
    upper = 500 * level ** 2
    names = ["Novice", "Explorer", "Adventurer", "Challenger", "Veteran", "Elite", "Master"]
    return {"level": level, "rank": names[min(level - 1, len(names) - 1)], "xp_into_level": total_xp - lower, "xp_for_level": upper - lower}


@app.post("/api/auth/register", status_code=201)
def register(data: Signup, request: Request, response: Response, session: Session = Depends(db_session)):
    rate_limit(session, request, "register", 10)
    email = str(data.email).lower()
    if session.scalar(select(User).where(User.email == email)): raise HTTPException(409, "Email is already registered")
    user = User(username=data.username.strip(), email=email, password_hash=passwords.hash(data.password))
    session.add(user); session.commit(); session.refresh(user); issue_cookie(response, user)
    return {"id": user.id, "username": user.username}


@app.post("/api/auth/login")
def login(data: AuthInput, request: Request, response: Response, session: Session = Depends(db_session)):
    rate_limit(session, request, "login", 10)
    user = session.scalar(select(User).where(User.email == str(data.email).lower()))
    if not user or not passwords.verify(data.password, user.password_hash): raise HTTPException(401, "Email or password is incorrect")
    issue_cookie(response, user); return {"id": user.id, "username": user.username}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie("sq_session"); return {"ok": True}


@app.get("/api/me")
def me(request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session)
    completed = session.scalars(select(Quest).where(Quest.user_id == user.id, Quest.status == "completed")).all()
    local_zone = ZoneInfo(user.timezone)
    days = sorted({(q.completed_at if q.completed_at.tzinfo else q.completed_at.replace(tzinfo=timezone.utc)).astimezone(local_zone).date() for q in completed if q.completed_at}, reverse=True)
    streak = 0
    if days:
        local_today = datetime.now(ZoneInfo(user.timezone)).date()
        if days[0] in (local_today, local_today - timedelta(days=1)):
            expected = days[0]
            for day in days:
                if day == expected: streak += 1; expected -= timedelta(days=1)
                else: break
    interests = [i.name for i in session.scalars(select(UserInterest).where(UserInterest.user_id == user.id)).all()]
    return {"id": user.id, "username": user.username, "xp": user.xp, **level_stats(user.xp), "streak": streak, "completed_count": len(completed), "interests": interests, "timezone": user.timezone}


QUESTS = {
    "daily": [("Take a 20-minute learning sprint", "Make progress on a skill you care about.", 35), ("Step outside and notice something new", "Take a mindful walk and capture one observation.", 30), ("Create a tiny thing", "Make a small sketch, note, or prototype.", 40)],
    "weekly": [("Make a one-hour project milestone", "Choose a meaningful goal and complete one visible step.", 100), ("Try a new activity", "Spend time exploring a new idea or place.", 90)],
    "monthly": [("Finish and share a personal project", "Build something across several short sessions and reflect on it.", 250)]
}


def seed_quest_templates(session: Session):
    for timeframe, templates in QUESTS.items():
        for slot, (title, description, xp) in enumerate(templates):
            key = f"starter:{timeframe}:{slot}"
            if not session.scalar(select(QuestTemplate.id).where(QuestTemplate.key == key)):
                session.add(QuestTemplate(key=key, title=title, description=description, timeframe=timeframe, category="Personal growth", estimated_minutes={"daily": 20, "weekly": 120, "monthly": 600}[timeframe], difficulty="Medium", base_xp=xp))
    session.commit()

INTEREST_TASKS = {
    "programming": {"daily": ("Solve a small coding challenge", "Practice one concept and note what you learned.", "Learning", 25, "Easy", 35), "weekly": ("Ship a small feature", "Build and document a useful feature in a project.", "Career", 120, "Medium", 100), "monthly": ("Publish a mini application", "Plan, build, test, and share a small complete app.", "Creative", 600, "Hard", 250)},
    "fitness": {"daily": ("Take a 20-minute movement break", "Choose a walk, stretch, or workout that feels good.", "Wellness", 20, "Easy", 35), "weekly": ("Try a new workout", "Pick a new session and reflect on what you enjoyed.", "Wellness", 90, "Medium", 100), "monthly": ("Build a four-week movement routine", "Choose a realistic routine and keep a simple progress log.", "Wellness", 480, "Hard", 250)},
    "photography": {"daily": ("Make one intentional photograph", "Find a subject and experiment with light or framing.", "Creativity", 20, "Easy", 35), "weekly": ("Complete a photo walk", "Explore a place and select your five favorite photos.", "Adventure", 120, "Medium", 100), "monthly": ("Create a themed photo story", "Collect and edit a small series around one visual theme.", "Creative", 600, "Hard", 250)},
    "reading": {"daily": ("Read for 20 focused minutes", "Put distractions away and capture one memorable idea.", "Learning", 20, "Easy", 35), "weekly": ("Finish a reading section", "Read a substantial section and write a short reflection.", "Learning", 120, "Medium", 100), "monthly": ("Finish a book and share a review", "Choose a book, make steady progress, then recommend it.", "Learning", 600, "Hard", 250)},
    "creativity": {"daily": ("Make a tiny creative study", "Spend a short session sketching, writing, or composing.", "Creative", 25, "Easy", 35), "weekly": ("Finish a small creative piece", "Make something complete enough to share with a friend.", "Creative", 150, "Medium", 100), "monthly": ("Build a personal portfolio piece", "Develop one larger piece through several focused sessions.", "Creative", 600, "Hard", 250)},
}


def quest_template(interest: str, timeframe: str, slot: int):
    match = INTEREST_TASKS.get(interest.lower())
    if match:
        title, desc, category, minutes, difficulty, xp = match[timeframe]
        return title, desc, category, minutes, difficulty, xp
    defaults = QUESTS[timeframe]
    title, desc, xp = defaults[slot % len(defaults)]
    mins = {"daily": 20, "weekly": 120, "monthly": 600}[timeframe]
    return title, desc, "Personal growth", mins, "Medium", xp


def current_period_key(frame: str, timezone_name: str = "UTC") -> str:
    try: today = datetime.now(ZoneInfo(timezone_name)).date()
    except ZoneInfoNotFoundError: today = datetime.now(timezone.utc).date()
    if frame == "daily": return today.isoformat()
    if frame == "weekly":
        iso = today.isocalendar(); return f"{iso.year}-W{iso.week:02d}"
    return today.strftime("%Y-%m")


def period_due_at(frame: str, timezone_name: str) -> datetime:
    from datetime import time
    zone = ZoneInfo(timezone_name)
    today = datetime.now(zone).date()
    if frame == "daily": end = today + timedelta(days=1)
    elif frame == "weekly": end = today + timedelta(days=7-today.weekday())
    else:
        end = today.replace(day=28) + timedelta(days=4)
        end = end.replace(day=1)
    return datetime.combine(end, time.min, tzinfo=zone).astimezone(timezone.utc)


def ensure_quests(user: User, session: Session):
    period_keys = {frame: current_period_key(frame, user.timezone) for frame in QUESTS}
    existing = {(q.timeframe, q.period_key, q.slot) for q in session.scalars(select(Quest).where(Quest.user_id == user.id)).all()}
    interests = [i.name for i in session.scalars(select(UserInterest).where(UserInterest.user_id == user.id)).all()]
    if not interests: return []
    for frame, rows in QUESTS.items():
        key = period_keys[frame]
        for slot, _ in enumerate(rows):
            if (frame, key, slot) not in existing:
                interest = interests[slot % len(interests)]
                title, desc, category, minutes, difficulty, xp = quest_template(interest, frame, slot)
                template_key = f"starter:{frame}:{slot % len(QUESTS[frame])}"
                template = session.scalar(select(QuestTemplate).where(QuestTemplate.key == template_key))
                session.add(Quest(user_id=user.id, template_id=template.id if template else None, title=title, description=desc, timeframe=frame, category=category, estimated_minutes=minutes, difficulty=difficulty, period_key=key, slot=slot, base_xp=xp, due_at=period_due_at(frame, user.timezone)))
    # Expire old active assignments and preserve them in history.
    for q in session.scalars(select(Quest).where(Quest.user_id == user.id, Quest.status == "active")).all():
        if q.period_key != period_keys[q.timeframe]: q.status = "expired"
    session.commit()
    return session.scalars(select(Quest).where(Quest.user_id == user.id).order_by(Quest.id.desc())).all()


@app.get("/api/quests")
def quests(request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session)
    if not session.scalar(select(UserInterest.id).where(UserInterest.user_id == user.id).limit(1)): return []
    ensure_quests(user, session)
    items = session.scalars(select(Quest).where(Quest.user_id == user.id, Quest.status.in_(["active", "completed"]), Quest.period_key.in_([current_period_key(f, user.timezone) for f in QUESTS])).order_by(Quest.id)).all()
    return [{"id": q.id, "title": q.title, "description": q.description, "timeframe": q.timeframe, "category": q.category, "estimated_minutes": q.estimated_minutes, "difficulty": q.difficulty, "xp": max(5, q.base_xp // (2 ** q.rerolls)), "status": q.status, "rerolls": q.rerolls, "progress": q.progress, "due_at": q.due_at.isoformat() if q.due_at else None} for q in items]


@app.get("/api/quest-templates")
def quest_templates(request: Request, session: Session = Depends(db_session)):
    get_user(request, session)
    return [{"id": t.id, "title": t.title, "description": t.description, "timeframe": t.timeframe, "category": t.category, "estimated_minutes": t.estimated_minutes, "difficulty": t.difficulty, "base_xp": t.base_xp} for t in session.scalars(select(QuestTemplate).order_by(QuestTemplate.timeframe, QuestTemplate.id)).all()]


@app.post("/api/quests/{quest_id}/complete")
def complete(quest_id: int, request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session)
    q = session.scalar(select(Quest).where(Quest.id == quest_id, Quest.user_id == user.id))
    if not q: raise HTTPException(404, "Quest not found")
    if q.status != "active": raise HTTPException(409, "Quest is no longer active")
    reward = max(5, q.base_xp // (2 ** q.rerolls)); q.status = "completed"; q.completed_at = datetime.now(timezone.utc); user.xp += reward
    session.add(XpLedger(user_id=user.id, quest_id=q.id, amount=reward, reason="quest_completion"))
    _award_achievements(user, session)
    session.commit(); return {"xp_earned": reward, "total_xp": user.xp, **level_stats(user.xp)}


@app.post("/api/quests/{quest_id}/reroll")
def reroll(quest_id: int, request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session)
    q = session.scalar(select(Quest).where(Quest.id == quest_id, Quest.user_id == user.id))
    if not q: raise HTTPException(404, "Quest not found")
    if q.status != "active" or q.rerolls >= 3: raise HTTPException(409, "This quest cannot be rerolled")
    q.rerolls += 1
    new_reward = max(5, q.base_xp // (2 ** q.rerolls))
    q.status = "rerolled"
    pool = QUESTS[q.timeframe]
    candidate = pool[(q.slot + q.generation + q.rerolls) % len(pool)]
    replacement = Quest(user_id=user.id, template_id=q.template_id, title=candidate[0], description=candidate[1], timeframe=q.timeframe, period_key=q.period_key, slot=q.slot, generation=q.generation + 1, difficulty=q.difficulty, base_xp=q.base_xp, rerolls=q.rerolls, due_at=q.due_at, category=q.category, estimated_minutes=q.estimated_minutes)
    session.add(replacement); session.commit(); session.refresh(replacement)
    return {"rerolls": q.rerolls, "xp": new_reward, "replacement_id": replacement.id}


@app.patch("/api/quests/{quest_id}/progress")
def update_progress(quest_id: int, payload: dict, request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session); q = session.scalar(select(Quest).where(Quest.id == quest_id, Quest.user_id == user.id))
    if not q: raise HTTPException(404, "Quest not found")
    if q.status != "active": raise HTTPException(409, "Quest is no longer active")
    q.progress = max(0, min(100, int(payload.get("progress", 0)))); session.commit()
    return {"progress": q.progress}


def _award_achievements(user: User, session: Session):
    completed_quests = session.scalars(select(Quest).where(Quest.user_id == user.id, Quest.status == "completed")).all()
    completed = len(completed_quests)
    local_zone = ZoneInfo(user.timezone)
    dates = sorted({(q.completed_at if q.completed_at.tzinfo else q.completed_at.replace(tzinfo=timezone.utc)).astimezone(local_zone).date() for q in completed_quests if q.completed_at}, reverse=True)
    seven_day_streak = False
    if dates:
        expected = dates[0]; run = 0
        for day in dates:
            if day == expected: run += 1; expected -= timedelta(days=1)
            else: break
        seven_day_streak = run >= 7
    definitions = [
        ("first_quest", "First Steps", "Complete your first quest.", completed >= 1),
        ("quest_10", "Quest Collector", "Complete ten quests.", completed >= 10),
        ("quest_100", "Century Club", "Complete one hundred quests.", completed >= 100),
        ("seven_day_streak", "Steady Adventurer", "Complete a quest on seven consecutive days.", seven_day_streak),
        ("monthly_quest", "Long Game", "Complete a monthly quest.", any(q.timeframe == "monthly" for q in completed_quests)),
    ]
    for key, name, desc, earned in definitions:
        ach = session.scalar(select(Achievement).where(Achievement.key == key))
        if not ach:
            ach = Achievement(key=key, name=name, description=desc); session.add(ach); session.flush()
        if earned and not session.scalar(select(UserAchievement).where(UserAchievement.user_id == user.id, UserAchievement.achievement_id == ach.id)):
            session.add(UserAchievement(user_id=user.id, achievement_id=ach.id))


@app.get("/api/history")
def history(request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session)
    ledger = {x.quest_id: x.amount for x in session.scalars(select(XpLedger).where(XpLedger.user_id == user.id)).all()}
    return [{"id":q.id,"title":q.title,"timeframe":q.timeframe,"status":q.status,"xp":ledger.get(q.id, 0),"completed_at":q.completed_at.isoformat() if q.completed_at else None} for q in session.scalars(select(Quest).where(Quest.user_id == user.id).order_by(Quest.id.desc()).limit(100)).all()]


@app.get("/api/achievements")
def achievements(request: Request, session: Session = Depends(db_session)):
    user=get_user(request,session)
    return [{"name":a.name,"description":a.description,"unlocked_at":ua.unlocked_at.isoformat()} for ua in session.scalars(select(UserAchievement).where(UserAchievement.user_id==user.id)).all() for a in [session.get(Achievement,ua.achievement_id)]]


@app.post("/api/auth/forgot-password")
def forgot(data: ForgotInput, request: Request, session: Session = Depends(db_session)):
    rate_limit(session, request, "forgot", 5)
    # Generic response avoids revealing whether an account exists.
    email = str(data.email).lower()
    if email:
        user = session.scalar(select(User).where(User.email == str(email).lower()))
        if user:
            code = f"{randbelow(1_000_000):06d}"
            session.add(ResetCode(user_id=user.id, digest=sha256(code.encode()).hexdigest(), expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)))
            session.commit()
            if os.getenv("SMTP_HOST"):
                try:
                    message = EmailMessage(); message["Subject"] = "Your Side Quests password reset code"; message["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USERNAME", "")); message["To"] = email
                    message.set_content(f"Your reset code is {code}. It expires in 10 minutes.")
                    with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", "587")), timeout=10) as smtp:
                        smtp.starttls()
                        if os.getenv("SMTP_USERNAME"): smtp.login(os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD", ""))
                        smtp.send_message(message)
                except Exception:
                    logger.exception("Password reset email delivery failed")
            else:
                logger.info("Development password reset code for %s: %s", email, code)
    return {"message": "If the account exists, reset instructions have been sent."}


@app.post("/api/auth/reset-password")
def reset_password(data: ResetInput, request: Request, session: Session = Depends(db_session)):
    rate_limit(session, request, "reset", 8)
    user = session.scalar(select(User).where(User.email == str(data.email).lower()))
    if not user: raise HTTPException(400, "Invalid or expired reset code")
    rows = session.scalars(select(ResetCode).where(ResetCode.user_id == user.id, ResetCode.used.is_(False)).order_by(ResetCode.id.desc())).all()
    now = datetime.now(timezone.utc)
    supplied = sha256(data.code.encode()).hexdigest()
    for item in rows:
        item.attempts += 1
        expiry = item.expires_at if item.expires_at.tzinfo else item.expires_at.replace(tzinfo=timezone.utc)
        if item.attempts <= 5 and expiry > now and item.digest == supplied:
            item.used = True
            user.password_hash = passwords.hash(data.new_password)
            session.commit()
            return {"message": "Password updated. You can now sign in."}
    session.commit()
    raise HTTPException(400, "Invalid or expired reset code")


@app.get("/api/interests")
def list_interests(request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session)
    return [i.name for i in session.scalars(select(UserInterest).where(UserInterest.user_id == user.id)).all()]


@app.put("/api/interests")
def set_interests(data: InterestInput, request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session)
    names = list(dict.fromkeys(i.strip() for i in data.interests if i.strip()))
    if not 1 <= len(names) <= 3: raise HTTPException(422, "Choose between one and three interests")
    session.query(UserInterest).filter_by(user_id=user.id).delete()
    session.add_all([UserInterest(user_id=user.id, name=n[:40]) for n in names])
    session.commit()
    return {"interests": names}


@app.patch("/api/profile")
def update_profile(data: ProfileInput, request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session)
    if data.username is not None: user.username = data.username.strip()
    if data.timezone is not None:
        try: ZoneInfo(data.timezone)
        except ZoneInfoNotFoundError: raise HTTPException(422, "Choose a valid IANA timezone, such as Europe/London")
        user.timezone = data.timezone
    session.commit()
    return {"username": user.username, "timezone": user.timezone}


@app.post("/api/auth/change-password")
def change_password(data: PasswordChange, request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session)
    if not passwords.verify(data.current_password, user.password_hash): raise HTTPException(400, "Current password is incorrect")
    user.password_hash = passwords.hash(data.new_password)
    session.commit()
    return {"message": "Password updated"}


@app.delete("/api/me", status_code=204)
def delete_account(request: Request, response: Response, session: Session = Depends(db_session)):
    user = get_user(request, session)
    for model in (UserAchievement, XpLedger, ResetCode, UserInterest, Quest):
        session.query(model).filter_by(user_id=user.id).delete(synchronize_session=False)
    session.delete(user); session.commit(); response.delete_cookie("sq_session")
    return Response(status_code=204)


@app.get("/api/progress/stats")
def progress_stats(request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session)
    quests = session.scalars(select(Quest).where(Quest.user_id == user.id)).all()
    summary = {}
    for frame in QUESTS:
        group = [q for q in quests if q.timeframe == frame]
        summary[frame] = {"assigned": len(group), "completed": sum(q.status == "completed" for q in group), "expired": sum(q.status == "expired" for q in group)}
    categories = {}
    for q in quests:
        bucket = categories.setdefault(q.category, {"assigned": 0, "completed": 0})
        bucket["assigned"] += 1
        bucket["completed"] += q.status == "completed"
    return {"total_xp": user.xp, "levels": level_stats(user.xp), "timeframes": summary, "categories": categories, "xp_history": [{"amount": x.amount, "reason": x.reason, "created_at": x.created_at.isoformat()} for x in session.scalars(select(XpLedger).where(XpLedger.user_id == user.id).order_by(XpLedger.id.desc()).limit(50)).all()]}
