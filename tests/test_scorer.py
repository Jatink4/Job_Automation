"""
tests/test_scorer.py — Unit tests for transparent multi-factor scoring engine.
"""

import asyncio
import pytest

from core.profiles import JobProfile
from core.scorer import (
    ScoreBreakdown,
    calculate_transparent_score,
    score_deterministic,
)


@pytest.fixture
def candidate_resume() -> dict:
    return {
        "skills": ["Python", "FastAPI", "React", "SQL", "Git", "Docker"],
        "projects": [
            {
                "name": "E-Commerce Microservice",
                "tech": ["Python", "FastAPI", "PostgreSQL"],
                "bullets": ["Designed scalable APIs using FastAPI"],
            }
        ],
        "job_preferences": {},
    }


@pytest.fixture
def profile_1() -> JobProfile:
    return JobProfile(
        id="profile_1",
        name="Full Stack Developer",
        target_titles=["Software Engineer", "Full Stack Developer", "Python Developer"],
        required_skills=["Python", "FastAPI", "React", "SQL"],
        secondary_skills=["Docker", "TypeScript"],
        min_salary=600000.0,
        currency="INR",
        preferred_locations=["Bangalore", "Remote"],
        min_experience_years=0,
        max_experience_years=3,
    )


def test_score_deterministic_high_fit(profile_1, candidate_resume):
    job = {
        "title": "Full Stack Python Developer",
        "company": "Growth Labs",
        "location": "Bangalore",
        "description": "We are seeking a Full Stack Developer with strong hands-on Python, FastAPI, React, and SQL experience.",
    }
    score_res = score_deterministic(job, profile_1, candidate_resume)
    assert isinstance(score_res, ScoreBreakdown)
    assert score_res.total_score >= 70
    assert score_res.skills_score > 20
    assert "Python" in score_res.matched_skills
    assert "FastAPI" in score_res.matched_skills
    assert len(score_res.pros) > 0


def test_score_deterministic_low_fit(profile_1, candidate_resume):
    job = {
        "title": "Senior Embedded Firmware Engineer",
        "company": "Chip Co",
        "location": "Dallas, TX",
        "description": "Requires 10+ years experience in C/C++, RTOS, hardware debugging, SPI/I2C protocols.",
    }
    score_res = score_deterministic(job, profile_1, candidate_resume)
    assert score_res.total_score < 50
    assert len(score_res.missing_skills) >= 2


def test_calculate_transparent_score_fallback(profile_1, candidate_resume):
    async def _test():
        job = {
            "title": "Python Backend Engineer",
            "company": "SaaS Platform",
            "location": "Remote",
            "description": "Building microservices with Python, FastAPI, and SQL.",
        }
        res = await calculate_transparent_score(job, profile_1, candidate_resume)
        assert isinstance(res, ScoreBreakdown)
        assert res.total_score >= 60
        assert "skills_score" in res.to_dict()

    asyncio.run(_test())
