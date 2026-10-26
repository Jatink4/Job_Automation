"""
core/db.py — Enhanced SQLite Database for Job Tracking & Application Management.

Maintains complete state for:
- Discovered jobs with stable URL & ID deduplication
- Hard-filter decisions & rejection reasons
- Transparent multi-factor match scores & breakdowns
- Review-Before-Submit application queue
- Complete application history and audit logs
- Manual application URLs for external listings
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger

import config

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), timeout=20.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize the SQLite schema with required tables and indexes."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                job_id TEXT NOT NULL,
                canonical_id TEXT NOT NULL UNIQUE,
                url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                company TEXT,
                location TEXT,
                salary_raw TEXT,
                employment_type TEXT,
                experience_level TEXT,
                profile_id TEXT NOT NULL,
                profile_name TEXT,
                description TEXT,
                hard_filter_passed INTEGER NOT NULL DEFAULT 1,
                rejection_reason TEXT,
                ai_score INTEGER DEFAULT 0,
                score_breakdown TEXT,
                easy_apply INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                manual_apply_url TEXT,
                tailored_cover_letter TEXT,
                resume_highlights TEXT,
                discovered_at TEXT NOT NULL,
                applied_at TEXT,
                error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS application_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT,
                company TEXT,
                action TEXT NOT NULL,
                notes TEXT,
                timestamp TEXT NOT NULL
            )
            """
        )
        # Indexes for fast lookup
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_profile ON jobs(profile_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(ai_score)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_canonical ON jobs(canonical_id)")
        conn.commit()
    logger.debug("Database initialized at {}", config.DB_PATH)


def clean_job_url(raw_url: str) -> str:
    """Strip tracking parameters to generate a stable, canonical URL."""
    if not raw_url:
        return ""
    # Remove LinkedIn tracking params like ?refId=..., trackingId=..., etc.
    base = raw_url.split("?")[0].strip()
    return base


def compute_canonical_id(source: str, job_id: str, url: str) -> str:
    """Generate stable canonical identifier."""
    cleaned_id = str(job_id).strip()
    if cleaned_id and cleaned_id != "None" and cleaned_id != "0":
        return f"{source}:{cleaned_id}"
    cleaned_url = clean_job_url(url)
    url_hash = hashlib.sha256(cleaned_url.encode("utf-8")).hexdigest()[:16]
    return f"{source}:hash_{url_hash}"


def is_job_duplicate(source: str, job_id: str, url: str) -> bool:
    """Return True if job was already discovered or recorded."""
    cid = compute_canonical_id(source, job_id, url)
    cleaned_url = clean_job_url(url)
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE canonical_id = ? OR url = ?",
            (cid, cleaned_url),
        ).fetchone()
    return row is not None


def record_discovered_job(
    job: dict[str, Any],
    profile_id: str = "profile_1",
    profile_name: str = "Default Profile",
    hard_filter_passed: bool = True,
    rejection_reason: str = "",
    score_breakdown: Optional[dict[str, Any]] = None,
    default_status: str = "review_pending",
) -> tuple[int, bool]:
    """
    Insert or update a discovered job in the database.
    Returns (job_row_id, is_new).
    """
    source = job.get("source", "linkedin")
    job_id = str(job.get("job_id", "")).strip()
    raw_url = job.get("url", "")
    cleaned_url = clean_job_url(raw_url) or f"urn:job:{source}:{job_id}"
    canonical_id = compute_canonical_id(source, job_id, cleaned_url)

    total_score = int(score_breakdown.get("total_score", 0)) if score_breakdown else int(job.get("ai_score") or 0)
    score_json = json.dumps(score_breakdown, ensure_ascii=False) if score_breakdown else ""

    status = "rejected" if not hard_filter_passed else default_status
    easy_apply = 1 if job.get("easy_apply") else 0
    now_iso = datetime.now().isoformat()

    with _connect() as conn:
        # Check if exists
        existing = conn.execute(
            "SELECT id, status FROM jobs WHERE canonical_id = ? OR url = ?",
            (canonical_id, cleaned_url),
        ).fetchone()

        if existing:
            job_db_id = existing["id"]
            conn.execute(
                """
                UPDATE jobs SET
                    title = ?,
                    company = ?,
                    location = ?,
                    salary_raw = ?,
                    ai_score = ?,
                    score_breakdown = ?,
                    hard_filter_passed = ?,
                    rejection_reason = ?,
                    easy_apply = ?
                WHERE id = ?
                """,
                (
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    job.get("salary_raw") or job.get("salary", ""),
                    total_score,
                    score_json,
                    1 if hard_filter_passed else 0,
                    rejection_reason,
                    easy_apply,
                    job_db_id,
                ),
            )
            conn.commit()
            return job_db_id, False

        cursor = conn.execute(
            """
            INSERT INTO jobs (
                source, job_id, canonical_id, url, title, company, location,
                salary_raw, employment_type, experience_level, profile_id,
                profile_name, description, hard_filter_passed, rejection_reason,
                ai_score, score_breakdown, easy_apply, status, manual_apply_url,
                discovered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                job_id,
                canonical_id,
                cleaned_url,
                job.get("title", "Untitled Job"),
                job.get("company", "Unknown"),
                job.get("location", ""),
                job.get("salary_raw") or job.get("salary", ""),
                job.get("employment_type", "Full-time"),
                job.get("experience_level", ""),
                profile_id,
                profile_name,
                job.get("description", ""),
                1 if hard_filter_passed else 0,
                rejection_reason,
                total_score,
                score_json,
                easy_apply,
                status,
                cleaned_url,
                now_iso,
            ),
        )
        job_db_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO application_history (job_id, source, title, company, action, notes, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                source,
                job.get("title", ""),
                job.get("company", ""),
                "discovered",
                f"Status: {status} | Score: {total_score}",
                now_iso,
            ),
        )
        conn.commit()
        return job_db_id, True


def update_job_status(job_db_id: int, new_status: str, notes: str = "", error: str = "") -> None:
    """Update job workflow status and record history event."""
    now_iso = datetime.now().isoformat()
    with _connect() as conn:
        job = conn.execute("SELECT job_id, source, title, company FROM jobs WHERE id = ?", (job_db_id,)).fetchone()
        if not job:
            return

        applied_at = now_iso if new_status in ("applied", "manual_applied") else None

        conn.execute(
            """
            UPDATE jobs SET
                status = ?,
                applied_at = COALESCE(?, applied_at),
                error = ?
            WHERE id = ?
            """,
            (new_status, applied_at, error, job_db_id),
        )
        conn.execute(
            """
            INSERT INTO application_history (job_id, source, title, company, action, notes, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["job_id"],
                job["source"],
                job["title"],
                job["company"],
                new_status,
                notes,
                now_iso,
            ),
        )
        conn.commit()


def save_assistant_notes(job_db_id: int, cover_letter: str = "", highlights: str = "") -> None:
    """Save tailored cover letter and resume highlights for a job."""
    with _connect() as conn:
        conn.execute(
            """
            UPDATE jobs SET
                tailored_cover_letter = COALESCE(NULLIF(?, ''), tailored_cover_letter),
                resume_highlights = COALESCE(NULLIF(?, ''), resume_highlights)
            WHERE id = ?
            """,
            (cover_letter, highlights, job_db_id),
        )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────
#  Dashboard & Inspection Queries
# ──────────────────────────────────────────────────────────────────────
def get_jobs_by_status(status: Optional[str] = None, profile_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Retrieve jobs filtered by status and/or profile."""
    query = "SELECT * FROM jobs WHERE 1=1"
    params: list[Any] = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if profile_id and profile_id != "all":
        query += " AND profile_id = ?"
        params.append(profile_id)
    query += " ORDER BY ai_score DESC, discovered_at DESC"

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_job_by_id(job_db_id: int) -> Optional[dict[str, Any]]:
    """Fetch a single job record by SQLite row id."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_db_id,)).fetchone()
        return dict(row) if row else None


def get_pending_review_jobs(profile_id: Optional[str] = None) -> list[dict[str, Any]]:
    return get_jobs_by_status(status="review_pending", profile_id=profile_id)


def get_matched_jobs(profile_id: Optional[str] = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM jobs WHERE hard_filter_passed = 1"
    params: list[Any] = []
    if profile_id and profile_id != "all":
        query += " AND profile_id = ?"
        params.append(profile_id)
    query += " ORDER BY ai_score DESC, discovered_at DESC"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_rejected_jobs(profile_id: Optional[str] = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM jobs WHERE status = 'rejected' OR hard_filter_passed = 0"
    params: list[Any] = []
    if profile_id and profile_id != "all":
        query += " AND profile_id = ?"
        params.append(profile_id)
    query += " ORDER BY discovered_at DESC"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_application_history(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM application_history
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_summary_metrics() -> dict[str, int]:
    """Return dashboard KPI counters."""
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        matched = conn.execute("SELECT COUNT(*) FROM jobs WHERE hard_filter_passed = 1").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'review_pending'").fetchone()[0]
        approved = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'approved'").fetchone()[0]
        applied = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('applied', 'manual_applied')").fetchone()[0]
        rejected = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'rejected' OR hard_filter_passed = 0").fetchone()[0]
        return {
            "total_discovered": total,
            "total_matched": matched,
            "pending_review": pending,
            "approved": approved,
            "total_applied": applied,
            "total_rejected": rejected,
        }


# ──────────────────────────────────────────────────────────────────────
#  Legacy Compatibility Shims
# ──────────────────────────────────────────────────────────────────────
def already_applied(source: str, job_id: str) -> bool:
    cid = compute_canonical_id(source, job_id, "")
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE (canonical_id = ? OR job_id = ?) AND status IN ('applied', 'manual_applied')",
            (cid, str(job_id)),
        ).fetchone()
    return row is not None


def should_skip_job(source: str, job_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT status FROM jobs WHERE job_id = ? AND source = ?",
            (str(job_id), source),
        ).fetchone()
    if not row:
        return False
    return row["status"] in ("applied", "manual_applied", "skipped", "rejected")


def record_application(job: dict[str, Any], status: str, error: str = "") -> None:
    source = job.get("source", "linkedin")
    job_id = str(job.get("job_id", ""))
    url = job.get("url", "")
    record_discovered_job(job, default_status=status)
    cid = compute_canonical_id(source, job_id, url)
    with _connect() as conn:
        row = conn.execute("SELECT id FROM jobs WHERE canonical_id = ?", (cid,)).fetchone()
        if row:
            update_job_status(row["id"], status, error=error)
