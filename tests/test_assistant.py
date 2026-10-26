"""
tests/test_assistant.py — Tests for truthful cover letter and resume assistance.
Verifies strictly grounded output without inventing qualifications.
"""

import pytest

from core.assistant import (
    generate_deterministic_cover_letter,
    generate_resume_highlights,
)
from core.profiles import JobProfile


@pytest.fixture
def candidate_resume() -> dict:
    return {
        "personal": {
            "name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "+91-9876543210",
            "location": "Bangalore, India",
        },
        "skills": ["Python", "FastAPI", "SQL", "Git"],
        "experience": [
            {
                "company": "Acme Innovations",
                "role": "Software Engineer Intern",
                "bullets": ["Engineered REST APIs using FastAPI and reduced response latency by 20%"],
            }
        ],
        "projects": [
            {
                "name": "Smart Task Manager",
                "tech": ["Python", "FastAPI", "SQLite"],
                "bullets": ["Implemented task scheduling pipeline with unit tests"],
            }
        ],
    }


@pytest.fixture
def sample_profile() -> JobProfile:
    return JobProfile(
        id="profile_1",
        name="Full Stack Developer",
        target_titles=["Software Engineer"],
        required_skills=["Python", "FastAPI", "SQL"],
        secondary_skills=["Docker"],
    )


def test_deterministic_cover_letter_content(candidate_resume, sample_profile):
    job = {
        "title": "Backend Python Developer",
        "company": "NextGen Software",
        "description": "Looking for a Python Developer experienced in FastAPI and SQL.",
    }
    letter = generate_deterministic_cover_letter(job, candidate_resume, sample_profile)

    assert "Jane Doe" in letter
    assert "NextGen Software" in letter
    assert "Acme Innovations" in letter
    assert "Smart Task Manager" in letter
    # Anti-hallucination check: must NOT contain fabricated credentials
    assert "PhD" not in letter
    assert "Google" not in letter
    assert "10 years" not in letter


def test_generate_resume_highlights(candidate_resume, sample_profile):
    job = {
        "title": "Python Developer",
        "company": "Tech Works",
        "description": "Looking for FastAPI and Python backend experience.",
    }
    highlights = generate_resume_highlights(job, candidate_resume, sample_profile)

    assert "key_bullets_to_emphasize" in highlights
    assert len(highlights["key_bullets_to_emphasize"]) > 0
    assert any("FastAPI" in b for b in highlights["key_bullets_to_emphasize"])
    assert "honest_skill_gaps" in highlights
