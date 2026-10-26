"""
core/filters.py — Strict Hard Filters for Job Discovery.

Evaluates every job against candidate profile hard constraints:
- Minimum salary threshold (with multi-format currency parsing)
- Location & workplace type (Remote / Hybrid / On-site)
- Work authorization & visa sponsorship eligibility
- Required skills coverage
- Experience ceiling / Seniority level
- Company and keyword blacklists
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from loguru import logger

from core.profiles import JobProfile


@dataclass
class FilterResult:
    passed: bool
    filter_name: str
    reason: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "filter_name": self.filter_name,
            "reason": self.reason,
            "details": self.details,
        }


def parse_salary_text(raw_text: str) -> tuple[Optional[float], Optional[float], str]:
    """
    Parse a salary string into (min_annual, max_annual, currency).
    Supports formats like:
      - "$80,000 - $120,000"
      - "12 - 15 LPA" or "8.5 Lacs"
      - "₹6,00,000 - ₹9,00,000"
      - "$50/hr" or "$50 - $70 per hour"
      - "€60k - €80k"
    """
    if not raw_text or not raw_text.strip():
        return None, None, ""

    text = raw_text.lower().replace(",", "").strip()

    # Detect currency
    currency = "USD" if "$" in raw_text else ("INR" if ("₹" in raw_text or "lpa" in text or "lac" in text or "inr" in text) else ("EUR" if "€" in raw_text else "UNKNOWN"))

    # Check for LPA / Lacs (Indian Lakhs per Annum: 1 Lakh = 100,000)
    lpa_matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:-|to)?\s*(\d+(?:\.\d+)?)?\s*(?:lpa|lakh|lac|lacs)", text)
    if lpa_matches:
        min_l, max_l = lpa_matches[0]
        min_val = float(min_l) * 100_000
        max_val = float(max_l) * 100_000 if max_l else min_val
        return min_val, max_val, "INR"

    # Check for hourly rates (assume 2,000 working hours/year)
    hourly_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)?\s*(\d+(?:\.\d+)?)?\s*(?:\/hr|per hour|hourly)", text)
    if hourly_match:
        min_h, max_h = hourly_match.groups()
        min_val = float(min_h) * 2000
        max_val = float(max_h) * 2000 if max_h else min_val
        return min_val, max_val, currency if currency != "UNKNOWN" else "USD"

    # Check for 'k' notation (e.g. 80k - 120k)
    k_matches = re.findall(r"(\d+(?:\.\d+)?)\s*k\b", text)
    if k_matches:
        vals = [float(x) * 1000 for x in k_matches]
        min_val = min(vals)
        max_val = max(vals)
        return min_val, max_val, currency if currency != "UNKNOWN" else "USD"

    # Standard integer/float numbers
    numbers = [float(x) for x in re.findall(r"\b\d{4,9}\b", text)]
    if numbers:
        return min(numbers), max(numbers), currency

    return None, None, currency


CITY_SYNONYMS: dict[str, list[str]] = {
    "bangalore": ["bangalore", "bengaluru", "blr", "karnataka"],
    "bengaluru": ["bangalore", "bengaluru", "blr", "karnataka"],
    "gurgaon": ["gurgaon", "gurugram", "ncr", "delhi", "delhi ncr", "haryana"],
    "gurugram": ["gurgaon", "gurugram", "ncr", "delhi", "delhi ncr", "haryana"],
    "delhi": ["delhi", "new delhi", "delhi ncr", "ncr", "noida", "gurgaon", "gurugram"],
    "noida": ["noida", "greater noida", "delhi", "delhi ncr", "delhi", "up"],
    "mumbai": ["mumbai", "bombay", "navi mumbai", "thane", "maharashtra"],
    "hyderabad": ["hyderabad", "secunderabad", "cyberabad", "telangana"],
    "pune": ["pune", "hinjewadi", "maharashtra"],
    "chennai": ["chennai", "madras", "tamil nadu"],
    "remote": ["remote", "work from home", "wfh", "anywhere", "pan india", "india"],
    "india": ["india", "pan india", "anywhere in india", "remote"],
}


def check_salary_filter(job: dict[str, Any], profile: JobProfile) -> FilterResult:
    """Validate that stated salary satisfies profile minimum (with soft leeway)."""
    if profile.min_salary is None or profile.min_salary <= 0:
        return FilterResult(True, "salary", "No minimum salary constraint configured", {})

    salary_raw = str(job.get("salary_raw") or job.get("salary") or "")
    if not salary_raw or any(x in salary_raw.lower() for x in ("not disclosed", "competitive", "best in industry", "as per")):
        # Undisclosed / standard market rates pass through to AI scoring
        return FilterResult(True, "salary", "Salary not specified / competitive (passed to scoring)", {"salary_raw": salary_raw})

    min_val, max_val, curr = parse_salary_text(salary_raw)
    if max_val is not None:
        # Soft threshold: Allow high-growth roles within 70% of target (e.g. 8.4L+ for 12L target)
        soft_floor = profile.min_salary * 0.70
        if max_val < soft_floor:
            return FilterResult(
                False,
                "salary",
                f"Offered salary ({salary_raw}) is below profile minimum ({soft_floor:,.0f} {profile.currency})",
                {"stated_min": min_val, "stated_max": max_val, "profile_min": profile.min_salary},
            )

    return FilterResult(
        True,
        "salary",
        f"Salary meets requirement ({salary_raw})",
        {"stated_min": min_val, "stated_max": max_val, "profile_min": profile.min_salary},
    )


def check_location_filter(job: dict[str, Any], profile: JobProfile) -> FilterResult:
    """Validate location and workplace policy (Remote, Hybrid, On-site) with Indian city normalization."""
    job_loc = str(job.get("location") or "").lower()
    job_title = str(job.get("title") or "").lower()
    job_desc = str(job.get("description") or "").lower()

    is_remote_job = (
        "remote" in job_loc
        or "remote" in job_title
        or "work from home" in job_loc
        or "wfh" in job_loc
        or bool(job.get("remote"))
    )

    # If profile requires Remote only
    if profile.location_type.lower() == "remote" and not is_remote_job:
        return FilterResult(
            False,
            "location",
            f"Candidate requires remote work, but job location is '{job.get('location', 'On-site')}'",
            {"job_location": job.get("location"), "required": "Remote"},
        )

    # If preferred locations specified, check overlap with synonyms
    pref_locs = [loc.lower() for loc in profile.preferred_locations if loc]
    if pref_locs and "any" not in pref_locs:
        # If job is in India and candidate accepts India / Remote
        if "india" in job_loc and ("india" in pref_locs or is_remote_job):
            return FilterResult(True, "location", "Matched India location", {"location": job.get("location")})

        if is_remote_job and any("remote" in l for l in pref_locs):
            return FilterResult(True, "location", "Matched preferred remote work", {"location": "Remote"})

        # Expand preferred locations with synonyms
        expanded_prefs = set()
        for loc in pref_locs:
            expanded_prefs.add(loc)
            if loc in CITY_SYNONYMS:
                expanded_prefs.update(CITY_SYNONYMS[loc])

        matches_location = any(pref in job_loc for pref in expanded_prefs)
        if not matches_location and not is_remote_job:
            # If job location is blank, pass to avoid dropping unparsed locations
            if not job_loc or job_loc == "unknown":
                return FilterResult(True, "location", "Location unstated (passed to scoring)", {})

            return FilterResult(
                False,
                "location",
                f"Job location '{job.get('location')}' does not match preferred locations: {', '.join(profile.preferred_locations)}",
                {"job_location": job.get("location"), "preferred": profile.preferred_locations},
            )

    return FilterResult(True, "location", f"Location criteria met ({job.get('location', 'Remote/Flexible')})", {})


def check_eligibility_filter(job: dict[str, Any], profile: JobProfile) -> FilterResult:
    """Check visa sponsorship and work authorization compatibility."""
    desc = str(job.get("description") or "").lower()

    if profile.requires_sponsorship:
        no_sponsorship_phrases = [
            "no visa sponsorship",
            "unable to sponsor",
            "not provide sponsorship",
            "without visa sponsorship",
            "must be a us citizen",
            "u.s. citizenship required",
            "green card holders only",
            "no c2c",
            "no corp to corp",
        ]
        for phrase in no_sponsorship_phrases:
            if phrase in desc:
                return FilterResult(
                    False,
                    "eligibility",
                    f"Candidate requires sponsorship, but job states: '{phrase}'",
                    {"matched_phrase": phrase},
                )

    return FilterResult(True, "eligibility", "Work authorization requirements satisfied", {})


def check_skills_filter(job: dict[str, Any], profile: JobProfile) -> FilterResult:
    """Ensure candidate has necessary critical skills and profile skills align."""
    req_skills = [s.lower() for s in profile.required_skills if s]
    if not req_skills:
        return FilterResult(True, "skills", "No mandatory skills configured in profile", {})

    desc = (str(job.get("description") or "") + " " + str(job.get("title") or "")).lower()

    # Find required skills mentioned in the job description
    demanded_skills = [s for s in req_skills if re.search(r"\b" + re.escape(s) + r"\b", desc)]

    # If the job explicitly targets this profile's domain, at least 1 primary skill must match
    title_l = str(job.get("title") or "").lower()
    title_overlap = any(t.lower() in title_l for t in profile.target_titles)

    if demanded_skills:
        return FilterResult(
            True,
            "skills",
            f"Profile required skills identified in job: {', '.join(demanded_skills)}",
            {"matched_required_skills": demanded_skills},
        )
    elif title_overlap:
        # Title matches profile, skill check passes
        return FilterResult(
            True,
            "skills",
            "Job title aligns directly with profile target titles",
            {"target_titles_matched": True},
        )

    return FilterResult(
        True,
        "skills",
        "Passed baseline skills review",
        {"matched_skills_count": len(demanded_skills)},
    )


def check_experience_filter(job: dict[str, Any], profile: JobProfile) -> FilterResult:
    """Check that seniority and experience expectations do not exceed candidate limits."""
    title_l = str(job.get("title") or "").lower()
    desc_l = str(job.get("description") or "").lower()

    # If candidate is entry/junior (max <= 3 years)
    if profile.max_experience_years <= 3:
        senior_indicators = [
            r"\b(10\+|8\+|7\+|6\+|5\+)\s*years?\b",
            r"\bprincipal\b",
            r"\barchitect\b",
            r"\bdirector\b",
            r"\bvp\b",
            r"\bhead of\b",
            r"\bstaff engineer\b",
        ]
        for pattern in senior_indicators:
            if re.search(pattern, title_l):
                return FilterResult(
                    False,
                    "experience",
                    f"Job title indicates senior/principal level exceeding candidate profile max ({profile.max_experience_years} yrs)",
                    {"matched_pattern": pattern, "target": "title"},
                )

    return FilterResult(True, "experience", "Experience level aligns with candidate profile", {})


def check_blacklist_filter(job: dict[str, Any], profile: JobProfile) -> FilterResult:
    """Check company and keyword blacklists."""
    company_l = str(job.get("company") or "").lower()
    title_l = str(job.get("title") or "").lower()
    desc_l = str(job.get("description") or "").lower()

    for bl_company in profile.blacklist_companies:
        if bl_company.lower() in company_l:
            return FilterResult(
                False,
                "blacklist_company",
                f"Company '{job.get('company')}' matches blacklist ('{bl_company}')",
                {"blacklisted_company": bl_company},
            )

    for bl_kw in profile.blacklist_keywords:
        bl_l = bl_kw.lower()
        if bl_l in title_l or bl_l in desc_l[:400]:
            return FilterResult(
                False,
                "blacklist_keyword",
                f"Job contains blacklisted keyword '{bl_kw}'",
                {"blacklisted_keyword": bl_kw},
            )

    return FilterResult(True, "blacklist", "No blacklisted companies or keywords found", {})


def evaluate_hard_filters(job: dict[str, Any], profile: JobProfile) -> tuple[bool, str, list[FilterResult]]:
    """
    Run all hard filters in sequence. Returns (all_passed, rejection_reason, results).
    """
    checks = [
        check_blacklist_filter,
        check_location_filter,
        check_salary_filter,
        check_eligibility_filter,
        check_experience_filter,
        check_skills_filter,
    ]

    results: list[FilterResult] = []
    for check_fn in checks:
        res = check_fn(job, profile)
        results.append(res)
        if not res.passed:
            logger.info("❌ Hard Filter FAILED for '{}': {} [{}]", job.get("title"), res.reason, res.filter_name)
            return False, res.reason, results

    return True, "", results
