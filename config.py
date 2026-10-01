"""Central configuration. Loads .env once and exposes typed settings."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()
GEMINI_FALLBACK_MODELS = [
    m.strip()
    for m in (os.getenv("GEMINI_FALLBACK_MODELS") or "gemini-2.0-flash").split(",")
    if m.strip()
]

SECRET_KEY = os.getenv("SECRET_KEY") or "dev-only-secret-change-me"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES") or 60)
SESSION_IDLE_MINUTES = 30

CORS_ORIGINS = [
    o.strip()
    for o in (os.getenv("CORS_ORIGINS") or "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if o.strip()
]

HOST = os.getenv("HOST") or "127.0.0.1"
PORT = int(os.getenv("PORT") or 8000)

DATA_DIR = Path(os.getenv("POCKETSMART_DATA_DIR") or (BASE_DIR / "data"))
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
