"""
config.py — Central configuration loader.

Reads secrets from .env, loads resume.json, and exposes typed settings
used throughout the project.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from loguru import logger

# ── Resolve project root (directory that contains this file) ────────────
BASE_DIR = Path(__file__).resolve().parent

# ── Load .env from project root ─────────────────────────────────────────
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")


# ──────────────────────────────────────────────────────────────────────
#  Secrets & environment variables
# ──────────────────────────────────────────────────────────────────────

# Google Gemini API (free tier available: 60 requests/minute, 1500 requests/day)
GEMINI_API_KEY: str = (os.getenv("GEMINI_API_KEY") or "").strip()

TELEGRAM_BOT_TOKEN: str = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID: str = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

LINKEDIN_EMAIL: str = (os.getenv("LINKEDIN_EMAIL") or "").strip()
LINKEDIN_PASSWORD: str = (os.getenv("LINKEDIN_PASSWORD") or "").strip()

NAUKRI_EMAIL: str = (os.getenv("NAUKRI_EMAIL") or "").strip()
NAUKRI_PASSWORD: str = (os.getenv("NAUKRI_PASSWORD") or "").strip()


# ──────────────────────────────────────────────────────────────────────
#  Bot behaviour defaults (overridable by .env)
# ──────────────────────────────────────────────────────────────────────
MAX_APPLICATIONS_PER_RUN: int = int(os.getenv("MAX_APPLICATIONS_PER_RUN", "10"))
DELAY_BETWEEN_APPS_MIN: int = int(os.getenv("DELAY_BETWEEN_APPS_MIN", "45"))
DELAY_BETWEEN_APPS_MAX: int = int(os.getenv("DELAY_BETWEEN_APPS_MAX", "90"))


# ──────────────────────────────────────────────────────────────────────
#  Paths
# ──────────────────────────────────────────────────────────────────────
RESUME_JSON_PATH: Path = BASE_DIR / "resume.json"
RESUME_PDF_PATH: Path = BASE_DIR / "resume.pdf"        # default; overridable in resume.json
DB_PATH: Path = BASE_DIR / "job_bot.db"
SCREENSHOTS_DIR: Path = BASE_DIR / "screenshots"
BROWSER_DATA_DIR: Path = BASE_DIR / "browser_data"      # persistent Chromium profile

# Ensure key directories exist
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────────────────────────────
#  Resume loader
# ──────────────────────────────────────────────────────────────────────
def load_resume() -> dict[str, Any]:
    """Load and return the resume.json data as a dict."""
    if not RESUME_JSON_PATH.exists():
        logger.error("resume.json not found at {}", RESUME_JSON_PATH)
        raise FileNotFoundError(f"resume.json not found at {RESUME_JSON_PATH}")

    with open(RESUME_JSON_PATH, "r", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)

    # Allow resume.json to override the PDF path
    pdf_override = data.get("resume_pdf_path")
    if pdf_override:
        resolved = (BASE_DIR / pdf_override).resolve()
        if resolved.exists():
            global RESUME_PDF_PATH
            RESUME_PDF_PATH = resolved
        else:
            logger.warning("resume_pdf_path '{}' in resume.json does not exist; using default", pdf_override)

    logger.info("Loaded resume for {}", data.get("personal", {}).get("name", "Unknown"))
    return data
