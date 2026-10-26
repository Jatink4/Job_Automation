"""
tests/test_profiles.py — Unit tests for multi-profile configuration management.
"""

import json
from pathlib import Path

import pytest

from core.profiles import (
    DEFAULT_PROFILES,
    JobProfile,
    get_profile,
    load_profiles,
    save_profiles,
)


def test_default_profiles_count():
    assert len(DEFAULT_PROFILES) == 3
    ids = [p["id"] for p in DEFAULT_PROFILES]
    assert "profile_1" in ids
    assert "profile_2" in ids
    assert "profile_3" in ids


def test_job_profile_serialization():
    p = JobProfile.from_dict(DEFAULT_PROFILES[0])
    assert p.id == "profile_1"
    assert "Python" in p.required_skills
    assert p.min_salary == 600000.0

    d = p.to_dict()
    assert isinstance(d, dict)
    assert d["name"] == p.name
    assert d["min_match_score"] == 65


def test_load_profiles_returns_three():
    profiles = load_profiles()
    assert len(profiles) >= 3
    p1 = get_profile("profile_1")
    assert p1 is not None
    assert "Software Engineer" in p1.target_titles or "Full Stack Developer" in p1.target_titles


def test_get_nonexistent_profile_returns_none():
    p = get_profile("profile_unknown_999")
    assert p is None
