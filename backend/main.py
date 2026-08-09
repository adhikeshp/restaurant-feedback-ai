import os
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from typing import Literal
import jwt
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from pwdlib import PasswordHash
from sqlalchemy import DateTime, Integer, String, Text, create_engine, select, desc, asc, case
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from services.llm_service import analyze_feedback

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://restaurant:restaurant@localhost:5432/restaurant_feedback")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine)
password_hash = PasswordHash.recommended()
security = HTTPBearer()

class Base(DeclarativeBase): pass
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="manager")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(120))
    feedback_text: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_issue: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority_score: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(20), default="complete")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class Submit(BaseModel): name: str = Field(min_length=1, max_length=120); feedback: str = Field(min_length=5, max_length=5000)
class Login(BaseModel): login_id: str; password: str
class Register(BaseModel):
    login_id: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)
def db():
    with SessionLocal() as s: yield s
def token_for(user: User):
    return jwt.encode({"sub": str(user.id), "exp": datetime.now(timezone.utc)+timedelta(hours=8)}, os.getenv("JWT_SECRET", "development-only-change-me"), algorithm="HS256")
def manager(c: HTTPAuthorizationCredentials=Depends(security), s: Session=Depends(db)):
    try: uid = int(jwt.decode(c.credentials, os.getenv("JWT_SECRET", "development-only-change-me"), algorithms=["HS256"])["sub"])
    except Exception: raise HTTPException(401, "Invalid or expired session")
    user=s.get(User, uid)
    if not user: raise HTTPException(401, "Invalid session")
    return user
def seed(s):
    if not s.scalar(select(User).where(User.login_id=="manager")): s.add(User(login_id="manager", password_hash=password_hash.hash("Manager@123")))
    if s.scalar(select(Feedback.id).limit(1)): s.commit(); return
    records=[("Aarav","I found a small piece of glass in my salad.","FOOD CONTAMINATION","CRITICAL",98),("Nisha","The fish tasted spoiled and I felt unwell after dinner.","FOOD QUALITY","HIGH",86),("Vikram","Our server was rude and ignored us for twenty minutes.","SERVER COMPLAINTS","HIGH",78),("Maya","The chairs near the window are uncomfortable.","SURROUNDING AMBIENCE","MEDIUM",54),("Rohan","Please consider adding more vegan desserts.","OTHERS","LOW",22),("Leena","There was hair in the pasta.","FOOD CONTAMINATION","CRITICAL",96),("Kabir","My soup arrived cold.","FOOD QUALITY","MEDIUM",60),("Isha","The dining room was far too noisy.","SURROUNDING AMBIENCE","MEDIUM",48),("Dev","Service was a little slow at lunch.","SERVER COMPLAINTS","MEDIUM",57),("Tara","Parking is difficult on weekends.","SURROUNDING AMBIENCE","LOW",28)]
    for n,t,cat,sev,score in records: s.add(Feedback(customer_name=n, feedback_text=t, category=cat, severity=sev, priority_score=score, summary=f"Customer reported {cat.lower()}.", key_issue=cat.title(), recommended_action="Review this concern with the responsible team."))
    s.commit()
@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with SessionLocal() as s: seed(s)
    yield
app=FastAPI(title="Table Service API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS","http://localhost:5173").split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
@app.post("/api/feedback")
async def submit(payload: Submit, s: Session=Depends(db)):
    row=Feedback(customer_name=payload.name.strip(), feedback_text=payload.feedback.strip(), processing_status="pending"); s.add(row); s.commit(); s.refresh(row)
    try:
        a=await analyze_feedback(row.feedback_text)
        for k,v in a.model_dump().items(): setattr(row,k,v)
        row.processing_status="complete"
    except Exception: row.processing_status="failed"
    s.commit(); return {"message":"Thank you for your feedback."}
@app.post("/api/auth/login")
def login(payload: Login, s: Session=Depends(db)):
    u=s.scalar(select(User).where(User.login_id==payload.login_id))
    if not u or not password_hash.verify(payload.password, u.password_hash): raise HTTPException(401,"Incorrect Login ID or password")
    return {"access_token":token_for(u),"token_type":"bearer"}
@app.post("/api/auth/register", status_code=201)
def register(payload: Register, s: Session=Depends(db)):
    login_id = payload.login_id.strip()
    if len(login_id) < 3: raise HTTPException(422, "Login ID must be at least 3 characters")
    if s.scalar(select(User).where(User.login_id == login_id)):
        raise HTTPException(409, "That Login ID is already in use")
    user = User(login_id=login_id, password_hash=password_hash.hash(payload.password))
    s.add(user); s.commit(); s.refresh(user)
    return {"message": "Staff account created successfully"}
@app.get("/api/feedback")
def list_feedback(category: str|None=None,severity: str|None=None,sort: Literal["priority","newest","oldest"]="priority", _=Depends(manager),s: Session=Depends(db)):
    q=select(Feedback).where(Feedback.processing_status=="complete")
    if category: q=q.where(Feedback.category==category)
    if severity: q=q.where(Feedback.severity==severity)
    severity_order=case({"CRITICAL":4,"HIGH":3,"MEDIUM":2,"LOW":1},value=Feedback.severity,else_=0)
    q=q.order_by(desc(severity_order),desc(Feedback.priority_score),desc(Feedback.created_at)) if sort=="priority" else q.order_by(desc(Feedback.created_at) if sort=="newest" else asc(Feedback.created_at))
    return [serialize(x) for x in s.scalars(q)]
@app.get("/api/feedback/stats")
def stats(_=Depends(manager),s: Session=Depends(db)):
    rows=list(s.scalars(select(Feedback).where(Feedback.processing_status=="complete"))); return {"total":len(rows),**{k.lower():sum(x.severity==k for x in rows) for k in ["CRITICAL","HIGH","MEDIUM","LOW"]}}
@app.get("/api/feedback/{feedback_id}")
def detail(feedback_id:int,_=Depends(manager),s:Session=Depends(db)):
    x=s.get(Feedback,feedback_id)
    if not x: raise HTTPException(404,"Feedback not found")
    return serialize(x)
def serialize(x): return {k:getattr(x,k) for k in ["id","customer_name","feedback_text","category","severity","summary","key_issue","recommended_action","priority_score","processing_status","created_at"]}
