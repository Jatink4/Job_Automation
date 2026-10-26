"""
tests/test_db.py — Unit tests for SQLite storage, URL deduplication, and workflow states.
"""

import os
import sqlite3
import pytest

import config
from core.db import (
    clean_job_url,
    compute_canonical_id,
    get_matched_jobs,
    get_pending_review_jobs,
    get_rejected_jobs,
    get_summary_metrics,
    init_db,
    is_job_duplicate,
    record_discovered_job,
    update_job_status,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db_path = tmp_path / "test_job_bot.db"
    monkeypatch.setattr(config, "DB_PATH", test_db_path)
    init_db()
    yield test_db_path


def test_clean_job_url():
    url = "https://www.linkedin.com/jobs/view/123456789/?refId=abc&trackingId=xyz"
    cleaned = clean_job_url(url)
    assert cleaned == "https://www.linkedin.com/jobs/view/123456789/"


def test_compute_canonical_id():
    cid = compute_canonical_id("linkedin", "123456789", "https://linkedin.com/jobs/view/123456789/")
    assert cid == "linkedin:123456789"


def test_record_and_duplicate_detection():
    job = {
        "source": "linkedin",
        "job_id": "999888111",
        "url": "https://www.linkedin.com/jobs/view/999888111/?trackingId=123",
        "title": "Software Engineer",
        "company": "Alpha Corp",
        "location": "Remote",
    }
    # First insert
    row_id, is_new = record_discovered_job(job, profile_id="profile_1")
    assert is_new is True
    assert row_id > 0

    # Verify duplicate is detected
    dup = is_job_duplicate("linkedin", "999888111", "https://www.linkedin.com/jobs/view/999888111/")
    assert dup is True

    # Re-recording should update without creating duplicate row
    row_id2, is_new2 = record_discovered_job(job, profile_id="profile_1")
    assert is_new2 is False
    assert row_id2 == row_id


def test_workflow_status_transitions():
    job = {
        "source": "linkedin",
        "job_id": "555444333",
        "url": "https://www.linkedin.com/jobs/view/555444333/",
        "title": "Python Backend Dev",
        "company": "Beta Corp",
        "ai_score": 85,
    }
    row_id, _ = record_discovered_job(job, profile_id="profile_1", default_status="review_pending")

    # Initial state
    pending = get_pending_review_jobs()
    assert any(j["id"] == row_id for j in pending)

    # Approve
    update_job_status(row_id, "approved", notes="Approved by user")
    pending = get_pending_review_jobs()
    assert not any(j["id"] == row_id for j in pending)

    # Summary metrics
    metrics = get_summary_metrics()
    assert metrics["approved"] >= 1
