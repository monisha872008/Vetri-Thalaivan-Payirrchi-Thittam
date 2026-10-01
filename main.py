"""
PocketSmart AI - FastAPI backend.

Run:  python main.py      (or)      uvicorn main:app --reload
"""
import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

import auth
import config
import gemini_utils
from models import HomeBudgetInput, JewelryBudgetInput, PartyBudgetInput, RegisterUser
from storage import history_store

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s: %(message)s")
logger = logging.getLogger("pocketsmart")

BASE_DIR = config.BASE_DIR
config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# In-memory session + token state (per server process)
active_sessions: Dict[str, Dict[str, Any]] = {}
blacklisted_tokens: Dict[str, float] = {}  # token -> expiry timestamp


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# App + lifespan (background cleanup of idle sessions / expired blacklist)
# --------------------------------------------------------------------------- #
async def cleanup_expired_sessions() -> None:
    while True:
        await asyncio.sleep(300)
        now = _now()
        for username in [
            u for u, s in active_sessions.items()
            if (now - s["last_activity"]).total_seconds() > config.SESSION_IDLE_MINUTES * 60
        ]:
            logger.info("Removing idle session for %s", username)
            active_sessions.pop(username, None)
        ts = now.timestamp()
        for token in [t for t, exp in blacklisted_tokens.items() if exp < ts]:
            blacklisted_tokens.pop(token, None)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not gemini_utils.ai_enabled():
        logger.warning("GEMINI_API_KEY not set - running in DEMO mode (built-in planner).")
    else:
        logger.info("Gemini enabled (model=%s)", config.GEMINI_MODEL)
    if config.SECRET_KEY.startswith("dev-only"):
        logger.warning("SECRET_KEY is not set - using an insecure development key.")
    task = asyncio.create_task(cleanup_expired_sessions())
    yield
    task.cancel()


app = FastAPI(title="PocketSmart: AI Budget Planner", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Browsers get redirected to /login on 401; API clients get JSON."""
    if exc.status_code == 401 and "text/html" in request.headers.get("accept", ""):
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie("access_token")
        return response
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


# --------------------------------------------------------------------------- #
# Auth dependencies
# --------------------------------------------------------------------------- #
def get_token(request: Request) -> Optional[str]:
    token = request.cookies.get("access_token")
    if token:
        return token
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def _user_from_request(request: Request) -> Optional[dict]:
    token = get_token(request)
    if not token or token in blacklisted_tokens:
        return None
    payload = auth.decode_token(token)
    if not payload:
        return None
    user = auth.get_user(payload.get("sub", ""))
    if not user:
        return None
    key = user["username"].lower()
    session = active_sessions.get(key)
    if session is None:
        session = active_sessions[key] = {"username": user["username"], "login_time": _now(), "user_data": {}}
    session["token"] = token
    session["last_activity"] = _now()
    return user


def get_current_user(request: Request) -> dict:
    user = _user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return user


def get_optional_user(request: Request) -> Optional[dict]:
    return _user_from_request(request)


def _session_for(user: dict) -> Dict[str, Any]:
    return active_sessions[user["username"].lower()]


def render(request: Request, name: str, user: Optional[dict] = None, **ctx):
    return templates.TemplateResponse(request, name, {"user": user, **ctx})


# --------------------------------------------------------------------------- #
# Public pages + auth
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user: Optional[dict] = Depends(get_optional_user)):
    return render(request, "index.html", user, active="home")


@app.get("/health")
async def health():
    return {"status": "ok", "ai_enabled": gemini_utils.ai_enabled(), "model": config.GEMINI_MODEL}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user: Optional[dict] = Depends(get_optional_user)):
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return render(request, "login.html", None, active="login")


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, user: Optional[dict] = Depends(get_optional_user)):
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return render(request, "register.html", None, active="register")


@app.post("/register", status_code=201)
async def register(data: RegisterUser):
    try:
        auth.create_user(data.username, data.email, data.password, data.full_name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"message": "Account created. You can sign in now."}


@app.post("/token")
async def login_for_access_token(username: str = Form(...), password: str = Form(...)):
    user = auth.authenticate_user(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = auth.create_access_token(user["username"])
    key = user["username"].lower()
    old = active_sessions.get(key)
    if old and old.get("token"):
        blacklisted_tokens[old["token"]] = _now().timestamp() + config.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    active_sessions[key] = {
        "username": user["username"],
        "login_time": _now(),
        "last_activity": _now(),
        "token": token,
        "user_data": old["user_data"] if old else {},
    }
    response = JSONResponse({"access_token": token, "token_type": "bearer"})
    response.set_cookie(
        "access_token", token, httponly=True, samesite="lax", max_age=config.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return response


@app.post("/logout")
async def logout(request: Request):
    token = get_token(request)
    if token:
        payload = auth.decode_token(token)
        if payload:
            blacklisted_tokens[token] = float(payload.get("exp", _now().timestamp()))
            active_sessions.pop(payload.get("sub", ""), None)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("access_token")
    return response


# --------------------------------------------------------------------------- #
# Session endpoints
# --------------------------------------------------------------------------- #
@app.get("/session-info")
async def session_info(user: dict = Depends(get_current_user)):
    s = _session_for(user)
    return {
        "username": s["username"],
        "login_time": s["login_time"].isoformat(),
        "last_activity": s["last_activity"].isoformat(),
        "session_duration_minutes": int((_now() - s["login_time"]).total_seconds() // 60),
        "user_data": s["user_data"],
    }


@app.post("/session-data")
async def update_session_data(data: Dict[str, Any], user: dict = Depends(get_current_user)):
    s = _session_for(user)
    s["user_data"].update(data)
    s["last_activity"] = _now()
    return {"message": "Session data updated", "data": s["user_data"]}


# --------------------------------------------------------------------------- #
# Planner pages
# --------------------------------------------------------------------------- #
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: dict = Depends(get_current_user)):
    return render(request, "dashboard.html", user, active="dashboard")


@app.get("/home-planner", response_class=HTMLResponse)
async def home_planner(request: Request, user: dict = Depends(get_current_user)):
    return render(request, "home_planner.html", user, active="home-planner")


@app.get("/party-planner", response_class=HTMLResponse)
async def party_planner(request: Request, user: dict = Depends(get_current_user)):
    return render(request, "party_planner.html", user, active="party-planner")


@app.get("/jewelry-planner", response_class=HTMLResponse)
async def jewelry_planner(request: Request, user: dict = Depends(get_current_user)):
    return render(request, "jewelry_planner.html", user, active="jewelry-planner")


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, user: dict = Depends(get_current_user)):
    return render(request, "history.html", user, active="history")


# --------------------------------------------------------------------------- #
# History helpers
# --------------------------------------------------------------------------- #
def save_to_history(username: str, rec_type: str, input_data: dict, result: dict) -> str:
    entry = {
        "id": uuid.uuid4().hex,
        "timestamp": _now().isoformat(),
        "type": rec_type,
        "input": input_data,
        "summary": {
            "total_budget": result.get("total_budget"),
            "remaining_budget": result.get("remaining_budget"),
            "categories": [c["category"] for c in result.get("budget_breakdown", [])],
            "source": result.get("source"),
        },
        "full_result": result,
    }
    data = history_store.load()
    entries = data.setdefault(username.lower(), [])
    entries.append(entry)
    data[username.lower()] = entries[-100:]
    history_store.save(data)
    return entry["id"]


def _remember(user: dict, key: str, payload: dict) -> None:
    s = _session_for(user)
    s["user_data"][key] = {"timestamp": _now().isoformat(), **payload}


# --------------------------------------------------------------------------- #
# Planner API
# --------------------------------------------------------------------------- #
@app.post("/generate-home")
def generate_home(budget_input: HomeBudgetInput, user: dict = Depends(get_current_user)):
    _remember(user, "last_home_budget", {"budget": budget_input.total_budget})
    try:
        result = gemini_utils.get_home_recommendations(budget_input)
    except Exception as exc:  # should not happen: the engine has its own fallback
        logger.exception("Home planner failed")
        raise HTTPException(status_code=500, detail=f"Error generating recommendations: {exc}")
    result["history_id"] = save_to_history(user["username"], "home", budget_input.model_dump(), result)
    return result


@app.post("/generate-party")
def generate_party(budget_input: PartyBudgetInput, user: dict = Depends(get_current_user)):
    _remember(user, "last_party_budget", {"budget": budget_input.total_budget, "guests": budget_input.num_guests})
    try:
        result = gemini_utils.get_party_recommendations(budget_input)
    except Exception as exc:
        logger.exception("Party planner failed")
        raise HTTPException(status_code=500, detail=f"Error generating recommendations: {exc}")
    result["history_id"] = save_to_history(user["username"], "party", budget_input.model_dump(), result)
    return result


def save_upload_file(upload: UploadFile) -> str:
    """Validate (real image, <=5 MB) and store an uploaded outfit photo."""
    data = upload.file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image is larger than 5 MB")
    try:
        Image.open(BytesIO(data)).verify()
        fmt = (Image.open(BytesIO(data)).format or "").lower()
    except Exception:
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid image")
    ext = {"jpeg": ".jpg", "png": ".png", "webp": ".webp"}.get(fmt)
    if not ext:
        raise HTTPException(status_code=400, detail="Use a JPG, PNG or WEBP image")
    name = f"{_now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    path = config.UPLOAD_DIR / name
    path.write_bytes(data)
    return str(path)


@app.post("/generate-jewelry")
def generate_jewelry(
    total_budget: float = Form(...),
    occasion: str = Form("Casual"),
    preferences: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user),
):
    try:
        budget_input = JewelryBudgetInput(total_budget=total_budget, occasion=occasion, preferences=preferences or None)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="; ".join(e["msg"] for e in exc.errors()))

    image_path = save_upload_file(image) if image is not None and image.filename else None
    _remember(user, "last_jewelry_budget", {"budget": total_budget, "occasion": occasion, "has_image": bool(image_path)})
    try:
        result = gemini_utils.get_jewelry_recommendations(budget_input, image_path)
    except Exception as exc:
        logger.exception("Jewelry planner failed")
        raise HTTPException(status_code=500, detail=f"Error generating recommendations: {exc}")
    input_data = {**budget_input.model_dump(), "has_image": bool(image_path)}
    result["history_id"] = save_to_history(user["username"], "jewelry", input_data, result)
    return result


# --------------------------------------------------------------------------- #
# History API
# --------------------------------------------------------------------------- #
@app.get("/history-data")
async def history_data(user: dict = Depends(get_current_user)):
    entries = history_store.load().get(user["username"].lower(), [])
    entries = sorted(entries, key=lambda e: e["timestamp"], reverse=True)
    return {"history": [{k: v for k, v in e.items() if k != "full_result"} for e in entries]}


@app.get("/recommendation-details/{recommendation_id}")
async def recommendation_details(recommendation_id: str, user: dict = Depends(get_current_user)):
    for entry in history_store.load().get(user["username"].lower(), []):
        if entry["id"] == recommendation_id:
            return entry
    raise HTTPException(status_code=404, detail="Recommendation not found")


if __name__ == "__main__":
    import uvicorn

    print("Starting PocketSmart: AI Budget Planner ...")
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
