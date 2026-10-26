"""
tests/test_discovery.py — Tests for discovery vetting and dry-run safety.
"""

import asyncio
import pytest

import config
from core.db import get_pending_review_jobs, get_rejected_jobs, init_db
from core.discovery import JobDiscoveryEngine
from core.profiles import JobProfile


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_discovery.db"
    monkeypatch.setattr(config, "DB_PATH", test_db)
    init_db()
    yield test_db


@pytest.fixture
def test_profile() -> JobProfile:
    return JobProfile(
        id="profile_1",
        name="Backend Python Dev",
        target_titles=["Python Developer", "Software Engineer"],
        required_skills=["Python", "FastAPI"],
        secondary_skills=["SQL"],
        min_salary=500000.0,
        currency="INR",
        preferred_locations=["Remote", "Bangalore"],
        min_match_score=60,
    )


@pytest.fixture
def candidate_resume() -> dict:
    return {
        "skills": ["Python", "FastAPI", "SQL", "Git"],
        "projects": [
            {
                "name": "Backend Service",
                "tech": ["Python", "FastAPI"],
                "bullets": ["Engineered high performance backend API"],
            }
        ],
        "job_preferences": {},
    }


def test_process_job_matching_flow(test_profile, candidate_resume):
    async def _run():
        engine = JobDiscoveryEngine(dry_run=True)
        raw_job = {
            "source": "linkedin",
            "job_id": "777111222",
            "url": "https://www.linkedin.com/jobs/view/777111222/",
            "title": "Software Engineer - Python Developer",
            "company": "Cloud Corp",
            "location": "Bangalore",
            "salary_raw": "7 - 10 LPA",
            "description": "Looking for a Python Developer proficient in FastAPI and SQL.",
        }
        res = await engine.process_job(raw_job, test_profile, candidate_resume)
        assert res["status"] == "matched"
        assert res["score"] >= 60

        # Verify deposited into review_pending queue
        pending = get_pending_review_jobs()
        assert len(pending) == 1
        assert pending[0]["title"] == raw_job["title"]

    asyncio.run(_run())


def test_process_job_rejected_by_salary(test_profile, candidate_resume):
    async def _run():
        engine = JobDiscoveryEngine(dry_run=True)
        raw_job = {
            "source": "linkedin",
            "job_id": "777111333",
            "url": "https://www.linkedin.com/jobs/view/777111333/",
            "title": "Python Developer",
            "company": "LowPay Corp",
            "location": "Bangalore",
            "salary_raw": "2 - 3 LPA",  # Below min 500000
            "description": "Python developer role.",
        }
        res = await engine.process_job(raw_job, test_profile, candidate_resume)
        assert res["status"] == "rejected_filter"

        # Verify recorded in rejected jobs log
        rejected = get_rejected_jobs()
        assert any(j["job_id"] == "777111333" for j in rejected)

    asyncio.run(_run())
