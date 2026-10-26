"""
tests/test_filters.py — Unit tests for hard constraints (Salary, Location, Eligibility, Skills, Blacklist).
"""

import pytest

from core.filters import (
    check_blacklist_filter,
    check_eligibility_filter,
    check_experience_filter,
    check_location_filter,
    check_salary_filter,
    evaluate_hard_filters,
    parse_salary_text,
)
from core.profiles import JobProfile


@pytest.fixture
def sample_profile() -> JobProfile:
    return JobProfile(
        id="test_profile",
        name="Test Engineer",
        target_titles=["Software Engineer", "Backend Developer"],
        required_skills=["Python", "SQL"],
        secondary_skills=["Docker"],
        min_salary=600000.0,
        currency="INR",
        preferred_locations=["Bangalore", "Remote"],
        location_type="Any",
        min_experience_years=0,
        max_experience_years=3,
        requires_sponsorship=False,
        blacklist_companies=["BadCompany Ltd"],
        blacklist_keywords=["unpaid internship", "commission only"],
    )


def test_parse_salary_formats():
    min_v, max_v, curr = parse_salary_text("10 - 15 LPA")
    assert min_v == 1000000.0
    assert max_v == 1500000.0
    assert curr == "INR"

    min_v, max_v, curr = parse_salary_text("$80,000 - $120,000")
    assert min_v == 80000.0
    assert max_v == 120000.0
    assert curr == "USD"

    min_v, max_v, curr = parse_salary_text("$50/hr")
    assert min_v == 100000.0
    assert max_v == 100000.0


def test_salary_filter_rejection(sample_profile):
    job = {
        "title": "Junior Python Dev",
        "salary_raw": "3 - 4 LPA",
    }
    res = check_salary_filter(job, sample_profile)
    assert res.passed is False
    assert "below profile minimum" in res.reason


def test_salary_filter_acceptance(sample_profile):
    job = {
        "title": "Python Dev",
        "salary_raw": "8 - 12 LPA",
    }
    res = check_salary_filter(job, sample_profile)
    assert res.passed is True


def test_location_filter_remote_preference(sample_profile):
    sample_profile.location_type = "Remote"
    onsite_job = {"title": "Python Dev", "location": "Chennai, On-site"}
    res = check_location_filter(onsite_job, sample_profile)
    assert res.passed is False

    remote_job = {"title": "Python Dev", "location": "Remote, Anywhere"}
    res = check_location_filter(remote_job, sample_profile)
    assert res.passed is True


def test_eligibility_filter_rejection(sample_profile):
    sample_profile.requires_sponsorship = True
    job = {
        "title": "Engineer",
        "description": "Must be a US Citizen. We cannot provide visa sponsorship.",
    }
    res = check_eligibility_filter(job, sample_profile)
    assert res.passed is False


def test_blacklist_company_rejection(sample_profile):
    job = {"title": "Software Engineer", "company": "BadCompany Ltd"}
    res = check_blacklist_filter(job, sample_profile)
    assert res.passed is False


def test_blacklist_keyword_rejection(sample_profile):
    job = {"title": "Unpaid Internship Software", "company": "Startup Corp"}
    res = check_blacklist_filter(job, sample_profile)
    assert res.passed is False


def test_seniority_ceiling_rejection(sample_profile):
    job = {"title": "Principal Architect / Director of Engineering"}
    res = check_experience_filter(job, sample_profile)
    assert res.passed is False


def test_evaluate_hard_filters_all_pass(sample_profile):
    good_job = {
        "title": "Software Engineer (Backend)",
        "company": "Tech Corp",
        "location": "Bangalore",
        "salary_raw": "8 - 10 LPA",
        "description": "Looking for a Software Engineer proficient in Python and SQL.",
    }
    passed, reason, _ = evaluate_hard_filters(good_job, sample_profile)
    assert passed is True
    assert reason == ""
