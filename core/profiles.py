"""
core/profiles.py — Multi-profile configuration manager.

Supports 3 independent configurable job profiles, each with its own
target titles, required skills, secondary skills, salary expectations,
locations, experience bounds, and screening answers.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from loguru import logger

import config

PROFILES_JSON_PATH: Path = config.BASE_DIR / "profiles.json"
PROFILES_EXAMPLE_JSON_PATH: Path = config.BASE_DIR / "profiles.example.json"


@dataclass
class JobProfile:
    id: str
    name: str
    target_titles: list[str]
    required_skills: list[str]
    secondary_skills: list[str] = field(default_factory=list)
    min_salary: Optional[float] = None
    currency: str = "INR"
    preferred_locations: list[str] = field(default_factory=lambda: ["Remote"])
    location_type: str = "Any"  # "Any", "Remote", "Hybrid", "On-site"
    experience_level: str = "Entry-level / Mid"
    min_experience_years: int = 0
    max_experience_years: int = 3
    employment_type: list[str] = field(default_factory=lambda: ["Full-time"])
    work_authorization: str = "Authorized"
    requires_sponsorship: bool = False
    min_match_score: int = 65
    blacklist_companies: list[str] = field(default_factory=list)
    blacklist_keywords: list[str] = field(default_factory=list)
    whitelist_keywords: list[str] = field(default_factory=list)
    screening_answers: dict[str, Any] = field(default_factory=dict)
    resume_pdf_path: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobProfile":
        valid_keys = cls.__dataclass_fields__.keys()  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


DEFAULT_PROFILES: list[dict[str, Any]] = [
    {
        "id": "profile_1",
        "name": "Full Stack & Python Developer",
        "target_titles": [
            "Software Engineer",
            "Full Stack Developer",
            "Python Developer",
            "Backend Engineer",
            "Junior Software Engineer",
        ],
        "required_skills": ["Python", "FastAPI", "React", "SQL", "Git"],
        "secondary_skills": ["TypeScript", "Docker", "REST APIs", "Node.js", "PostgreSQL"],
        "min_salary": 600000.0,
        "currency": "INR",
        "preferred_locations": ["Bangalore", "Hyderabad", "Pune", "Remote"],
        "location_type": "Any",
        "experience_level": "Entry-level / Mid",
        "min_experience_years": 0,
        "max_experience_years": 3,
        "employment_type": ["Full-time", "Contract"],
        "work_authorization": "Authorized",
        "requires_sponsorship": False,
        "min_match_score": 65,
        "blacklist_companies": ["Revature", "CyberCoders"],
        "blacklist_keywords": ["unpaid", "commission only", "10+ years", "director", "principal"],
        "whitelist_keywords": ["software", "python", "full stack", "backend", "developer", "engineer"],
        "screening_answers": {
            "years_of_experience": "2",
            "notice_period": "Immediate",
            "expected_salary": "700000",
            "work_authorization": "Yes",
            "sponsorship_required": "No",
        },
    },
    {
        "id": "profile_2",
        "name": "Data Engineer & Machine Learning",
        "target_titles": [
            "Data Engineer",
            "Machine Learning Engineer",
            "AI Engineer",
            "Python Data Engineer",
            "Junior Data Scientist",
        ],
        "required_skills": ["Python", "Pandas", "SQL", "Machine Learning", "PyTorch"],
        "secondary_skills": ["Docker", "FastAPI", "Scikit-Learn", "ETL", "Spark"],
        "min_salary": 700000.0,
        "currency": "INR",
        "preferred_locations": ["Bangalore", "Gurgaon", "Mumbai", "Remote"],
        "location_type": "Any",
        "experience_level": "Entry-level / Associate",
        "min_experience_years": 0,
        "max_experience_years": 3,
        "employment_type": ["Full-time"],
        "work_authorization": "Authorized",
        "requires_sponsorship": False,
        "min_match_score": 65,
        "blacklist_companies": [],
        "blacklist_keywords": ["unpaid", "crypto trading", "phd required", "lead researcher"],
        "whitelist_keywords": ["data", "machine learning", "ai", "etl", "python", "pipeline"],
        "screening_answers": {
            "years_of_experience": "2",
            "notice_period": "15 days",
            "expected_salary": "800000",
            "work_authorization": "Yes",
            "sponsorship_required": "No",
        },
    },
    {
        "id": "profile_3",
        "name": "DevOps & Cloud Engineer",
        "target_titles": [
            "DevOps Engineer",
            "Cloud Engineer",
            "Site Reliability Engineer",
            "Platform Engineer",
            "Associate Cloud Architect",
        ],
        "required_skills": ["AWS", "Docker", "Linux", "CI/CD", "Python"],
        "secondary_skills": ["Kubernetes", "Terraform", "GitHub Actions", "Bash", "Prometheus"],
        "min_salary": 650000.0,
        "currency": "INR",
        "preferred_locations": ["Bangalore", "Hyderabad", "Noida", "Remote"],
        "location_type": "Any",
        "experience_level": "Associate / Mid",
        "min_experience_years": 0,
        "max_experience_years": 3,
        "employment_type": ["Full-time"],
        "work_authorization": "Authorized",
        "requires_sponsorship": False,
        "min_match_score": 65,
        "blacklist_companies": [],
        "blacklist_keywords": ["unpaid", "on-call 24/7 without compensation", "manager"],
        "whitelist_keywords": ["cloud", "devops", "aws", "docker", "ci/cd", "infrastructure"],
        "screening_answers": {
            "years_of_experience": "2",
            "notice_period": "Immediate",
            "expected_salary": "750000",
            "work_authorization": "Yes",
            "sponsorship_required": "No",
        },
    },
]


def create_example_profiles_file() -> None:
    """Create profiles.example.json if it doesn't exist."""
    if not PROFILES_EXAMPLE_JSON_PATH.exists():
        with open(PROFILES_EXAMPLE_JSON_PATH, "w", encoding="utf-8") as fh:
            json.dump({"profiles": DEFAULT_PROFILES}, fh, indent=2, ensure_ascii=False)
        logger.info("Created {}", PROFILES_EXAMPLE_JSON_PATH)


def load_profiles() -> list[JobProfile]:
    """
    Load job profiles from profiles.json. If missing, automatically initialize
    from profiles.example.json or default 3 profiles.
    """
    create_example_profiles_file()

    target_file = PROFILES_JSON_PATH if PROFILES_JSON_PATH.exists() else PROFILES_EXAMPLE_JSON_PATH
    if not target_file.exists():
        raw_list = DEFAULT_PROFILES
    else:
        try:
            with open(target_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                raw_list = data.get("profiles", [])
                if not raw_list:
                    raw_list = DEFAULT_PROFILES
        except Exception as exc:
            logger.warning("Failed to parse profiles file {}: {}. Using defaults.", target_file, exc)
            raw_list = DEFAULT_PROFILES

    profiles = [JobProfile.from_dict(p) for p in raw_list]
    return profiles


def get_profile(profile_id: str) -> Optional[JobProfile]:
    """Retrieve a specific profile by ID (e.g. 'profile_1')."""
    profiles = load_profiles()
    for p in profiles:
        if p.id.lower() == profile_id.lower():
            return p
    return None


def save_profiles(profiles: list[JobProfile]) -> None:
    """Save profile list to profiles.json."""
    data = {"profiles": [p.to_dict() for p in profiles]}
    with open(PROFILES_JSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    logger.info("Saved {} profiles to {}", len(profiles), PROFILES_JSON_PATH)
