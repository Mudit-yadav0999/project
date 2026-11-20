import json, os, uuid, base64, datetime as dt
from pathlib import Path
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
UPLOADS = ROOT / "backend" / "uploads"; UPLOADS.mkdir(exist_ok=True, parents=True)
engine = create_engine(f"sqlite:///{ROOT/'backend'/'kisan.db'}", connect_args={"check_same_thread": False})
Session_ = sessionmaker(bind=engine); Base = declarative_base()

class Farm(Base):
    __tablename__ = "farms"
    id = Column(Integer, primary_key=True); name = Column(String, nullable=False)
    crop = Column(String, nullable=False); variety = Column(String, default="")
    area_acres = Column(Float, nullable=False); soil = Column(String, default="")
    irrigation = Column(String, default=""); planted_on = Column(String, default="")
    stage = Column(String, default="sowing"); notes = Column(Text, default="")
class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True); title = Column(String, nullable=False)
    due = Column(String, nullable=False); crop = Column(String, default="")
    done = Column(Boolean, default=False)
class Scan(Base):
    __tablename__ = "scans"
    id = Column(Integer, primary_key=True); created = Column(DateTime, default=dt.datetime.utcnow)
    image = Column(String); crop = Column(String, default=""); problem = Column(String, default="")
    severity = Column(String, default=""); result = Column(Text, default="{}")
    favorite = Column(Boolean, default=False); notes = Column(Text, default="")
Base.metadata.create_all(engine)

def db():
    s = Session_()
    try: yield s
    finally: s.close()

app = FastAPI(title="Kisan Sathi API", version="0.1")

@app.get("/api/health")
def health():
    return {"status": "ok", "ai_configured": bool(os.getenv("AI_API_KEY")), "weather": "open-meteo (no key needed)"}

def row(o): return {c.name: getattr(o, c.name) for c in o.__table__.columns}

# ---- Farms ----
class FarmIn(BaseModel):
    name: str = Field(min_length=1, max_length=80); crop: str = Field(min_length=1)
    variety: str = ""; area_acres: float = Field(gt=0, le=100000); soil: str = ""
    irrigation: str = ""; planted_on: str = ""; stage: str = "sowing"; notes: str = ""
@app.get("/api/farms")
def farms(s: Session = Depends(db)): return [row(f) for f in s.query(Farm).all()]
@app.post("/api/farms")
def add_farm(b: FarmIn, s: Session = Depends(db)):
    f = Farm(**b.model_dump()); s.add(f); s.commit(); return row(f)
@app.put("/api/farms/{i}")
def edit_farm(i: int, b: FarmIn, s: Session = Depends(db)):
    f = s.get(Farm, i) or HTTPException(404, "Farm not found")
    if isinstance(f, HTTPException): raise f
    for k, v in b.model_dump().items(): setattr(f, k, v)
    s.commit(); return row(f)
@app.delete("/api/farms/{i}")
def del_farm(i: int, s: Session = Depends(db)):
    f = s.get(Farm, i)
    if not f: raise HTTPException(404, "Farm not found")
    s.delete(f); s.commit(); return {"deleted": i}

# ---- Tasks ----
class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=120); due: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    crop: str = ""; done: bool = False
@app.get("/api/tasks")
def tasks(s: Session = Depends(db)): return [row(t) for t in s.query(Task).order_by(Task.due).all()]
@app.post("/api/tasks")
def add_task(b: TaskIn, s: Session = Depends(db)):
    t = Task(**b.model_dump()); s.add(t); s.commit(); return row(t)
@app.put("/api/tasks/{i}")
def edit_task(i: int, b: TaskIn, s: Session = Depends(db)):
    t = s.get(Task, i)
    if not t: raise HTTPException(404, "Task not found")
    for k, v in b.model_dump().items(): setattr(t, k, v)
    s.commit(); return row(t)
@app.delete("/api/tasks/{i}")
def del_task(i: int, s: Session = Depends(db)):
    t = s.get(Task, i)
    if not t: raise HTTPException(404, "Task not found")
    s.delete(t); s.commit(); return {"deleted": i}

# ---- Scans (real vision model; no fabricated numbers) ----
PROMPT = """You are an agronomy assistant for Indian farmers. Look at the plant photo(s).
Reply with ONLY JSON: {"diagnosable": bool, "crop": str, "problem": str, "category": "disease|pest|nutrient deficiency|water stress|environmental stress|healthy|unknown",
"severity": "low|medium|high|unknown", "symptoms": [str], "cause": str, "risks": str, "next_action": str,
"immediate": [str], "treatment": [str], "organic": [str], "chemical": "only label-based, crop-specific guidance; say 'follow the product label and consult your local Krishi Vigyan Kendra'; no doses unless certain", "prevention": [str], "recovery": str, "precautions": [str],
"confidence_note": "one honest sentence on how certain you are and why"}.
If the photo is unclear or not a plant, set diagnosable=false and put in next_action what photo to retake. Never invent numeric confidence. Reply in the language code: """
ALLOWED = {"image/jpeg", "image/png", "image/webp"}

@app.post("/api/scans")
async def scan(files: list[UploadFile] = File(...), lang: str = Form("en"), details: str = Form(""), s: Session = Depends(db)):
    key = os.getenv("AI_API_KEY")
    if not key:
        raise HTTPException(503, "AI is not configured. Add AI_API_KEY to the .env file and restart the backend.")
    if not 1 <= len(files) <= 4: raise HTTPException(400, "Send 1 to 4 images.")
    content, saved = [], None
    for f in files:
        data = await f.read()
        if f.content_type not in ALLOWED: raise HTTPException(400, f"{f.filename}: use JPG, PNG or WebP.")
        if len(data) > 8_000_000: raise HTTPException(400, f"{f.filename}: image is larger than 8 MB.")
        name = f"{uuid.uuid4().hex}.{f.content_type.split('/')[1]}"
        (UPLOADS / name).write_bytes(data); saved = saved or name
        content.append({"type": "image", "source": {"type": "base64", "media_type": f.content_type, "data": base64.b64encode(data).decode()}})
    content.append({"type": "text", "text": PROMPT + lang + (f"\nFarmer notes: {details}" if details else "")})
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                json={"model": os.getenv("AI_MODEL", "claude-sonnet-4-6"), "max_tokens": 1800, "messages": [{"role": "user", "content": content}]})
        r.raise_for_status()
        text = r.json()["content"][0]["text"].strip().removeprefix("```json").removesuffix("```").strip()
        res = json.loads(text)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"AI provider returned {e.response.status_code}. Check AI_API_KEY and AI_MODEL.")
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(502, "Could not get a usable answer from the AI provider. Try again.")
    rec = Scan(image=saved, crop=res.get("crop", ""), problem=res.get("problem", ""), severity=res.get("severity", ""), result=json.dumps(res))
    s.add(rec); s.commit()
    return {**row(rec), "result": res}

@app.get("/api/scans")
def scans(q: str = "", s: Session = Depends(db)):
    qs = s.query(Scan).order_by(Scan.created.desc())
    if q: qs = qs.filter((Scan.crop.ilike(f"%{q}%")) | (Scan.problem.ilike(f"%{q}%")))
    return [{**row(x), "result": json.loads(x.result)} for x in qs.all()]
@app.patch("/api/scans/{i}")
def patch_scan(i: int, favorite: bool | None = None, notes: str | None = None, s: Session = Depends(db)):
    x = s.get(Scan, i)
    if not x: raise HTTPException(404, "Scan not found")
    if favorite is not None: x.favorite = favorite
    if notes is not None: x.notes = notes
    s.commit(); return row(x)
@app.delete("/api/scans/{i}")
def del_scan(i: int, s: Session = Depends(db)):
    x = s.get(Scan, i)
    if not x: raise HTTPException(404, "Scan not found")
    s.delete(x); s.commit(); return {"deleted": i}

# ---- Weather: real data from Open-Meteo ----
@app.get("/api/weather")
async def weather(place: str):
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            g = (await c.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": place, "count": 1})).json()
            if not g.get("results"): raise HTTPException(404, "Place not found. Try a nearby town name.")
            p = g["results"][0]
            w = (await c.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": p["latitude"], "longitude": p["longitude"], "timezone": "auto", "forecast_days": 7,
                "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum"})).json()
    except httpx.HTTPError:
        raise HTTPException(502, "Weather service is unreachable. Check your internet connection.")
    cur, d = w["current"], w["daily"]; advice = []
    if sum(d["precipitation_sum"][:3]) >= 10: advice.append("Rain expected in the next 3 days: delay irrigation and spraying.")
    elif sum(d["precipitation_sum"][:3]) < 1 and cur["temperature_2m"] > 30: advice.append("Hot and dry: irrigate in early morning or evening.")
    if max(d["temperature_2m_max"]) >= 40: advice.append("Heat warning: protect seedlings and avoid midday field work.")
    if min(d["temperature_2m_min"]) <= 4: advice.append("Frost risk: cover sensitive crops at night.")
    if cur["relative_humidity_2m"] > 80 and 20 <= cur["temperature_2m"] <= 30: advice.append("Warm and humid: fungal diseases spread easily. Inspect leaves often.")
    return {"place": f'{p["name"]}, {p.get("admin1","")}', "current": cur, "daily": d, "advice": advice}

# ---- Water calculator: Blaney-Criddle style ET0 x crop coefficient (an estimate) ----
KC = {"wheat": [0.4, 0.8, 1.15, 0.4], "rice": [1.05, 1.1, 1.2, 0.9], "maize": [0.4, 0.8, 1.2, 0.6],
      "cotton": [0.4, 0.8, 1.15, 0.7], "tomato": [0.5, 0.8, 1.15, 0.8], "potato": [0.5, 0.8, 1.15, 0.75],
      "sugarcane": [0.4, 0.9, 1.25, 0.75]}
STAGES = ["initial", "development", "mid", "late"]
EFF = {"drip": 0.9, "sprinkler": 0.75, "flood": 0.55}
class WaterIn(BaseModel):
    crop: str; area_acres: float = Field(gt=0); temp_c: float = Field(ge=-5, le=55)
    humidity: float = Field(ge=0, le=100); rain_mm_week: float = Field(ge=0, default=0)
    stage: str; irrigation: str
@app.post("/api/water")
def water(b: WaterIn):
    if b.crop not in KC or b.stage not in STAGES or b.irrigation not in EFF: raise HTTPException(400, "Unsupported crop, stage or irrigation method.")
    et0 = 0.27 * (0.46 * b.temp_c + 8) * (1.1 - 0.3 * b.humidity / 100)   # mm/day, estimate
    etc = et0 * KC[b.crop][STAGES.index(b.stage)]
    weekly_net = max(etc * 7 - 0.8 * b.rain_mm_week, 0)
    litres_week = weekly_net / EFF[b.irrigation] * b.area_acres * 4046.86
    tips = ["Irrigate early morning to cut evaporation.", "Mulch to keep soil moisture."]
    if b.irrigation == "flood": tips.append("Switching to drip can save about 30-40% water for many crops.")
    return {"et0_mm_day": round(et0, 2), "crop_mm_day": round(etc, 2), "daily_litres": round(litres_week / 7),
            "weekly_litres": round(litres_week), "method": "ET0 (Blaney-Criddle style estimate) x crop coefficient / irrigation efficiency",
            "tips": tips}

app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")
@app.get("/")
def index(): return FileResponse(ROOT / "frontend" / "index.html")
