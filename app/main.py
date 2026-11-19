import os
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from pathlib import Path
from secrets import randbelow
from hashlib import sha256

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator
from pwdlib import PasswordHash
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

BASE = Path(__file__).parent
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sidequests.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(engine, expire_on_commit=False)
passwords = PasswordHash.recommended()
app = FastAPI(title="Side Quests", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


class Base(DeclarativeBase): pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    xp: Mapped[int] = mapped_column(Integer, default=0)


class Quest(Base):
    __tablename__ = "user_quests"
    __table_args__ = (UniqueConstraint("user_id", "timeframe", "period_key", "slot", "generation", name="uq_user_quest_period_slot"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(String(500))
    timeframe: Mapped[str] = mapped_column(String(10))
    period_key: Mapped[str] = mapped_column(String(20), default="")
    slot: Mapped[int] = mapped_column(Integer, default=0)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    difficulty: Mapped[str] = mapped_column(String(20), default="Medium")
    base_xp: Mapped[int] = mapped_column(Integer, default=50)
    rerolls: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
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


@app.on_event("startup")
def startup():
    if os.getenv("APP_ENV", "development") == "production" and (not os.getenv("SECRET_KEY") or os.getenv("SECRET_KEY") == "dev-only-change-me"):
        raise RuntimeError("Set a strong SECRET_KEY before production startup")
    if os.getenv("APP_ENV", "development") != "production":
        Base.metadata.create_all(engine)


@app.get("/")
def home(): return FileResponse(BASE / "static" / "index.html")


@app.get("/health")
def health(): return {"status": "ok"}


def get_user(request, session: Session) -> User:
    from hmac import new, compare_digest
    token = request.cookies.get("sq_session", "")
    try:
        uid, sig = token.split(".", 1)
        expected = new(os.getenv("SECRET_KEY", "dev-only-change-me").encode(), uid.encode(), "sha256").hexdigest()
        if not compare_digest(sig, expected): raise ValueError()
        user = session.get(User, int(uid))
        if user: return user
    except Exception: pass
    raise HTTPException(401, "Please sign in")


def issue_cookie(response: Response, user: User):
    from hmac import new
    uid = str(user.id)
    sig = new(os.getenv("SECRET_KEY", "dev-only-change-me").encode(), uid.encode(), "sha256").hexdigest()
    response.set_cookie("sq_session", f"{uid}.{sig}", httponly=True, samesite="lax", secure=os.getenv("COOKIE_SECURE", "false").lower() == "true", max_age=60 * 60 * 24 * 7)


@app.post("/api/auth/register", status_code=201)
def register(data: Signup, response: Response, session: Session = Depends(db_session)):
    email = str(data.email).lower()
    if session.scalar(select(User).where(User.email == email)): raise HTTPException(409, "Email is already registered")
    user = User(username=data.username.strip(), email=email, password_hash=passwords.hash(data.password))
    session.add(user); session.commit(); session.refresh(user); issue_cookie(response, user)
    return {"id": user.id, "username": user.username}


@app.post("/api/auth/login")
def login(data: AuthInput, response: Response, session: Session = Depends(db_session)):
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
    days = sorted({q.completed_at.date() for q in completed if q.completed_at}, reverse=True)
    streak = 0
    if days:
        from datetime import date
        expected = date.today()
        if days[0] < expected: expected = days[0]
        for day in days:
            if day == expected: streak += 1; expected -= timedelta(days=1)
            else: break
    interests = [i.name for i in session.scalars(select(UserInterest).where(UserInterest.user_id == user.id)).all()]
    return {"id": user.id, "username": user.username, "xp": user.xp, "level": user.xp // 500 + 1, "xp_into_level": user.xp % 500, "rank": ["Novice", "Explorer", "Adventurer", "Challenger", "Veteran", "Elite", "Master"][min(user.xp // 500, 6)], "streak": streak, "completed_count": len(completed), "interests": interests}


QUESTS = {
    "daily": [("Take a 20-minute learning sprint", "Make progress on a skill you care about.", 35), ("Step outside and notice something new", "Take a mindful walk and capture one observation.", 30), ("Create a tiny thing", "Make a small sketch, note, or prototype.", 40)],
    "weekly": [("Make a one-hour project milestone", "Choose a meaningful goal and complete one visible step.", 100), ("Try a new activity", "Spend time exploring a new idea or place.", 90)],
    "monthly": [("Finish and share a personal project", "Build something across several short sessions and reflect on it.", 250)]
}


def current_period_key(frame: str) -> str:
    from datetime import date
    today = date.today()
    if frame == "daily": return today.isoformat()
    if frame == "weekly":
        iso = today.isocalendar(); return f"{iso.year}-W{iso.week:02d}"
    return today.strftime("%Y-%m")


def ensure_quests(user: User, session: Session):
    from datetime import date
    period_keys = {frame: current_period_key(frame) for frame in QUESTS}
    existing = {(q.timeframe, q.period_key, q.slot) for q in session.scalars(select(Quest).where(Quest.user_id == user.id)).all()}
    interests = [i.name for i in session.scalars(select(UserInterest).where(UserInterest.user_id == user.id)).all()] or ["Curiosity"]
    for frame, rows in QUESTS.items():
        key = period_keys[frame]
        for slot, (title, desc, xp) in enumerate(rows):
            if (frame, key, slot) not in existing:
                session.add(Quest(user_id=user.id, title=title.replace("your", interests[slot % len(interests)]), description=desc, timeframe=frame, period_key=key, slot=slot, base_xp=xp))
    # Expire old active assignments and preserve them in history.
    for q in session.scalars(select(Quest).where(Quest.user_id == user.id, Quest.status == "active")).all():
        if q.period_key != period_keys[q.timeframe]: q.status = "expired"
    session.commit()
    return session.scalars(select(Quest).where(Quest.user_id == user.id).order_by(Quest.id.desc())).all()


@app.get("/api/quests")
def quests(request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session)
    ensure_quests(user, session)
    items = session.scalars(select(Quest).where(Quest.user_id == user.id, Quest.period_key.in_([current_period_key(f) for f in QUESTS])).order_by(Quest.id)).all()
    return [{"id": q.id, "title": q.title, "description": q.description, "timeframe": q.timeframe, "difficulty": q.difficulty, "xp": max(5, q.base_xp // (2 ** q.rerolls)), "status": q.status, "rerolls": q.rerolls} for q in items]


@app.post("/api/quests/{quest_id}/complete")
def complete(quest_id: int, request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session)
    q = session.scalar(select(Quest).where(Quest.id == quest_id, Quest.user_id == user.id))
    if not q: raise HTTPException(404, "Quest not found")
    if q.status != "active": raise HTTPException(409, "Quest is no longer active")
    reward = max(5, q.base_xp // (2 ** q.rerolls)); q.status = "completed"; q.completed_at = datetime.now(timezone.utc); user.xp += reward
    session.add(XpLedger(user_id=user.id, quest_id=q.id, amount=reward, reason="quest_completion"))
    _award_achievements(user, session)
    session.commit(); return {"xp_earned": reward, "total_xp": user.xp, "level": user.xp // 500 + 1}


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
    replacement = Quest(user_id=user.id, title=candidate[0], description=candidate[1], timeframe=q.timeframe, period_key=q.period_key, slot=q.slot, generation=q.generation + 1, difficulty="Medium", base_xp=q.base_xp, rerolls=q.rerolls)
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
    completed = session.scalar(select(Quest).where(Quest.user_id == user.id, Quest.status == "completed").count()) if False else len(session.scalars(select(Quest).where(Quest.user_id == user.id, Quest.status == "completed")).all())
    definitions = [("first_quest", "First Steps", "Complete your first quest.", completed >= 1), ("quest_10", "Quest Collector", "Complete ten quests.", completed >= 10), ("monthly_quest", "Long Game", "Complete a monthly quest.", any(q.timeframe == "monthly" for q in session.scalars(select(Quest).where(Quest.user_id == user.id, Quest.status == "completed")).all()))]
    for key, name, desc, earned in definitions:
        ach = session.scalar(select(Achievement).where(Achievement.key == key))
        if not ach:
            ach = Achievement(key=key, name=name, description=desc); session.add(ach); session.flush()
        if earned and not session.scalar(select(UserAchievement).where(UserAchievement.user_id == user.id, UserAchievement.achievement_id == ach.id)):
            session.add(UserAchievement(user_id=user.id, achievement_id=ach.id))


@app.get("/api/history")
def history(request: Request, session: Session = Depends(db_session)):
    user = get_user(request, session); return [{"id":q.id,"title":q.title,"timeframe":q.timeframe,"status":q.status,"xp":q.base_xp,"completed_at":q.completed_at.isoformat() if q.completed_at else None} for q in session.scalars(select(Quest).where(Quest.user_id == user.id).order_by(Quest.id.desc()).limit(100)).all()]


@app.get("/api/achievements")
def achievements(request: Request, session: Session = Depends(db_session)):
    user=get_user(request,session)
    return [{"name":a.name,"description":a.description,"unlocked_at":ua.unlocked_at.isoformat()} for ua in session.scalars(select(UserAchievement).where(UserAchievement.user_id==user.id)).all() for a in [session.get(Achievement,ua.achievement_id)]]


@app.post("/api/auth/forgot-password")
def forgot(data: ForgotInput, session: Session = Depends(db_session)):
    # Generic response avoids revealing whether an account exists.
    email = str(data.email).lower()
    if email:
        user = session.scalar(select(User).where(User.email == str(email).lower()))
        if user:
            code = f"{randbelow(1_000_000):06d}"
            session.add(ResetCode(user_id=user.id, digest=sha256(code.encode()).hexdigest(), expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)))
            session.commit()
            if os.getenv("SMTP_HOST"):
                message = EmailMessage(); message["Subject"] = "Your Side Quests password reset code"; message["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USERNAME", "")); message["To"] = email
                message.set_content(f"Your reset code is {code}. It expires in 10 minutes.")
                with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", "587"))) as smtp:
                    smtp.starttls()
                    if os.getenv("SMTP_USERNAME"): smtp.login(os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD", ""))
                    smtp.send_message(message)
            else:
                print(f"Development password reset code for {email}: {code}")
    return {"message": "If the account exists, reset instructions have been sent."}


@app.post("/api/auth/reset-password")
def reset_password(data: ResetInput, session: Session = Depends(db_session)):
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
