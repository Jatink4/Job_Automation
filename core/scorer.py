"""
core/scorer.py — Multi-tier Transparent Match Scoring Engine.

Provides transparent, explainable 0–100 matching scores with dimensional breakdowns:
1. Skills Alignment (0–40 pts)
2. Experience & Title Fit (0–30 pts)
3. Domain & Project Fit (0–20 pts)
4. Logistics & Preferences (0–10 pts)

Supported scoring backends:
- Local Ollama (100% free & local, e.g. llama3.2, mistral, qwen2.5)
- Google Gemini (free quota tier: 60 req/min)
- Free Local Deterministic Matcher (offline, rule-based, zero configuration needed)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import requests
from loguru import logger

import config
from core.profiles import JobProfile


@dataclass
class ScoreBreakdown:
    total_score: int
    skills_score: int
    experience_score: int
    domain_score: int
    logistics_score: int
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    reasoning: str = ""
    provider: str = "Local Engine"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────
#  Skill Aliases & Robust Text Matching
# ──────────────────────────────────────────────────────────────────────
SKILL_ALIASES: dict[str, list[str]] = {
    "c++": [r"(?<!\w)c\+\+(?!\w)", r"\bcpp\b", r"(?<!\w)c/c\+\+(?!\w)", r"\bc\s+plus\s+plus\b"],
    "c": [r"(?<!\w)c(?!\w)"],
    "react.js": [r"\breact(?:\.js|js)?\b"],
    "react": [r"\breact(?:\.js|js)?\b"],
    "node.js": [r"\bnode(?:\.js|js)?\b"],
    "node": [r"\bnode(?:\.js|js)?\b"],
    "express.js": [r"\bexpress(?:\.js|js)?\b"],
    "express": [r"\bexpress(?:\.js|js)?\b"],
    "rest apis": [r"\brest(?:ful)?(?:\s+apis?|\s+services?|\s+architecture)?\b", r"\brest\b"],
    "rest api": [r"\brest(?:ful)?(?:\s+apis?|\s+services?|\s+architecture)?\b", r"\brest\b"],
    "mongodb": [r"\bmongo(?:db)?\b"],
    "sql": [r"\bsql\b", r"\bmysql\b", r"\bpostgresql\b", r"\bpostgres\b", r"\bsqlite\b"],
    "fastapi": [r"\bfastapi\b"],
    "rag": [r"\brag\b", r"\bretrieval[\s-]augmented\s+generation\b"],
    "retrieval-augmented generation": [r"\brag\b", r"\bretrieval[\s-]augmented\s+generation\b"],
    "llm": [r"\bllms?\b", r"\blarge\s+language\s+models?\b"],
    "ai agents": [r"\bai\s+agents?\b", r"\bagentic(?:\s+ai)?\b"],
    "power bi": [r"\bpower\s*bi\b"],
    "pandas": [r"\bpandas\b"],
    "numpy": [r"\bnumpy\b"],
    "data cleaning": [r"\bdata\s+cleaning\b", r"\bdata\s+preprocessing\b"],
    "exploratory data analysis (eda)": [r"\beda\b", r"\bexploratory\s+data\s+analysis\b"],
    "eda": [r"\beda\b", r"\bexploratory\s+data\s+analysis\b"],
    "feature engineering": [r"\bfeature\s+engineering\b"],
    "statistical analysis": [r"\bstat(?:istical|istics)?\s+analysis\b", r"\bstatistics\b"],
    "mece": [r"\bmece\b"],
    "tam/sam/som": [r"\btam\b", r"\bmarket\s+sizing\b"],
    "gtm strategy": [r"\bgtm\b", r"\bgo[\s-]to[\s-]market\b"],
    "market research": [r"\bmarket\s+research\b"],
    "financial modeling": [r"\bfinancial\s+model(?:ing)?\b"],
    "root cause analysis": [r"\broot[\s-]cause\b", r"\brca\b"],
    "kpi reporting": [r"\bkpis?\b", r"\bkpi\s+reporting\b"],
    "dashboard development": [r"\bdashboards?\b", r"\bdashboard\s+development\b"],
    "oop": [r"\boop\b", r"\bobject[\s-]oriented\b"],
    "object-oriented programming (oop)": [r"\boop\b", r"\bobject[\s-]oriented\b"],
    "dsa": [r"\bdsa\b", r"\bdata\s+structures\b"],
    "data structures & algorithms": [r"\bdsa\b", r"\bdata\s+structures\b"],
    "dbms": [r"\bdbms\b", r"\bdatabase\s+management\b"],
    "operating systems": [r"\boperating\s+systems?\b"],
    "computer networks": [r"\bcomputer\s+networks?\b", r"\bnetworking\b"],
}


def skill_matches(skill: str, text: str) -> bool:
    """Check if a skill (or its common abbreviations/variants) appears in text."""
    s_clean = skill.strip().lower()
    if s_clean in SKILL_ALIASES:
        return any(re.search(pat, text, re.IGNORECASE) for pat in SKILL_ALIASES[s_clean])
    escaped = re.escape(s_clean)
    pat = r"(?<!\w)" + escaped + r"(?!\w)"
    return bool(re.search(pat, text, re.IGNORECASE))


# ──────────────────────────────────────────────────────────────────────
#  1. Free Local Deterministic Matcher (Zero API keys needed)
# ──────────────────────────────────────────────────────────────────────
def score_deterministic(
    job: dict[str, Any],
    profile: JobProfile,
    resume: dict[str, Any],
) -> ScoreBreakdown:
    """
    Transparent, 100% offline rule-based scoring engine.
    Always available without API keys, accounts, or external services.
    """
    title = str(job.get("title") or "").strip()
    company = str(job.get("company") or "").strip()
    desc = (str(job.get("description") or "") + " " + title).lower()
    candidate_skills = [s.strip() for s in resume.get("skills", []) if s.strip()]
    profile_required = profile.required_skills
    profile_secondary = profile.secondary_skills

    # ── Dimension 1: Skills Alignment (max 40) ──────────────────────────
    matched_skills: list[str] = []
    missing_skills: list[str] = []

    # Check required skills against posting text
    req_hits = 0
    for s in profile_required:
        if skill_matches(s, desc):
            matched_skills.append(s)
            req_hits += 1
        else:
            missing_skills.append(s)

    # Check candidate resume skills that match job description
    candidate_hits = 0
    for s in candidate_skills:
        if not any(skill_matches(s, m) for m in matched_skills):
            if skill_matches(s, desc):
                matched_skills.append(s)
                candidate_hits += 1

    # Skill score computation
    req_ratio = (req_hits / max(len(profile_required), 1))
    skills_score = int(round(req_ratio * 25 + min(candidate_hits * 3, 15)))
    skills_score = max(0, min(40, skills_score))

    # ── Dimension 2: Experience & Title Fit (max 30) ────────────────────
    title_l = title.lower()
    title_score = 10  # baseline
    matched_target_title = False
    for target in profile.target_titles:
        if target.lower() in title_l:
            title_score = 22
            matched_target_title = True
            break
        target_words = set(target.lower().split())
        title_words = set(title_l.split())
        common = target_words.intersection(title_words)
        if len(common) >= 2:
            title_score = max(title_score, 18)
            matched_target_title = True

    # Experience alignment
    exp_bonus = 8
    if any(x in title_l for x in ("senior", "lead", "principal", "manager", "director")):
        if profile.max_experience_years <= 3:
            exp_bonus = 2  # penalty for excessive seniority
    elif any(x in title_l for x in ("junior", "associate", "entry", "fresher", "intern")):
        exp_bonus = 8  # perfect fit for junior/mid

    experience_score = min(30, title_score + exp_bonus)

    # ── Dimension 3: Domain & Project Fit (max 20) ──────────────────────
    domain_score = 10
    projects = resume.get("projects", [])
    project_techs: list[str] = []
    for p in projects:
        project_techs.extend(p.get("tech", []))

    proj_hits = 0
    for pt in project_techs:
        if skill_matches(pt, desc):
            proj_hits += 1

    domain_score = min(20, 10 + min(proj_hits * 3, 10))

    # ── Dimension 4: Logistics & Preferences (max 10) ───────────────────
    logistics_score = 5
    job_loc = str(job.get("location") or "").lower()
    if "remote" in job_loc or bool(job.get("remote")):
        logistics_score += 5
    elif any(pref.lower() in job_loc for pref in profile.preferred_locations):
        logistics_score += 5

    total = min(100, skills_score + experience_score + domain_score + logistics_score)

    # Build Pros & Cons
    pros: list[str] = []
    cons: list[str] = []

    if matched_target_title:
        pros.append(f"Title matches target profile '{profile.name}'")
    if matched_skills:
        pros.append(f"Candidate matched skills: {', '.join(matched_skills[:5])}")
    if "remote" in job_loc:
        pros.append("Remote-friendly position")

    if missing_skills and skills_score < 20:
        cons.append(f"Job posting does not explicitly cite: {', '.join(missing_skills[:4])}")
    elif skills_score < 20:
        cons.append("Limited direct skill overlap found in posting text")

    reasoning = (
        f"Score {total}/100: Skills ({skills_score}/40, {len(matched_skills)} matched), "
        f"Title/Role Fit ({experience_score}/30), Domain ({domain_score}/20), Logistics ({logistics_score}/10)."
    )

    return ScoreBreakdown(
        total_score=total,
        skills_score=skills_score,
        experience_score=experience_score,
        domain_score=domain_score,
        logistics_score=logistics_score,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        pros=pros,
        cons=cons,
        reasoning=reasoning,
        provider="Free Local Deterministic Engine",
    )


# ──────────────────────────────────────────────────────────────────────
#  2. Local Ollama Integration
# ──────────────────────────────────────────────────────────────────────
def is_ollama_available(host: str = "http://localhost:11434") -> tuple[bool, list[str]]:
    """Check if local Ollama daemon is running and retrieve installed models."""
    try:
        resp = requests.get(f"{host}/api/tags", timeout=1.5)
        if resp.status_code == 200:
            models_data = resp.json().get("models", [])
            names = [m.get("name", "").split(":")[0] for m in models_data if m.get("name")]
            return True, names
    except Exception:
        pass
    return False, []


def score_with_ollama(
    job: dict[str, Any],
    profile: JobProfile,
    resume: dict[str, Any],
    model: str = "llama3.2",
    host: str = "http://localhost:11434",
) -> Optional[ScoreBreakdown]:
    """Query local Ollama for structured resume-job evaluation."""
    available, models = is_ollama_available(host)
    if not available:
        return None

    # Pick available model if requested not found
    chosen_model = model
    if model not in models and models:
        chosen_model = models[0]

    prompt = (
        "You are an expert technical hiring manager evaluating candidate fit.\n"
        "Evaluate the candidate resume against the job description for the given profile.\n"
        "Respond with ONLY valid JSON with no markdown wrapping:\n"
        "{\n"
        '  "total_score": <int 0-100>,\n'
        '  "skills_score": <int 0-40>,\n'
        '  "experience_score": <int 0-30>,\n'
        '  "domain_score": <int 0-20>,\n'
        '  "logistics_score": <int 0-10>,\n'
        '  "matched_skills": ["skill1", "skill2"],\n'
        '  "missing_skills": ["skillA"],\n'
        '  "pros": ["strength 1", "strength 2"],\n'
        '  "cons": ["gap 1"],\n'
        '  "reasoning": "1-2 sentence overall summary"\n'
        "}\n\n"
        f"Target Profile: {profile.name} (Required skills: {profile.required_skills})\n"
        f"Job Title: {job.get('title')}\n"
        f"Company: {job.get('company')}\n"
        f"Location: {job.get('location')}\n"
        f"Job Description:\n{str(job.get('description') or '')[:1800]}\n\n"
        f"Candidate Resume Data:\n{json.dumps(resume, ensure_ascii=False)[:1800]}"
    )

    try:
        payload = {
            "model": chosen_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        res = requests.post(f"{host}/api/generate", json=payload, timeout=30)
        if res.status_code == 200:
            raw_text = res.json().get("response", "").strip()
            data = json.loads(raw_text)
            return ScoreBreakdown(
                total_score=max(0, min(100, int(data.get("total_score", 0)))),
                skills_score=max(0, min(40, int(data.get("skills_score", 0)))),
                experience_score=max(0, min(30, int(data.get("experience_score", 0)))),
                domain_score=max(0, min(20, int(data.get("domain_score", 0)))),
                logistics_score=max(0, min(10, int(data.get("logistics_score", 0)))),
                matched_skills=list(data.get("matched_skills", [])),
                missing_skills=list(data.get("missing_skills", [])),
                pros=list(data.get("pros", [])),
                cons=list(data.get("cons", [])),
                reasoning=str(data.get("reasoning", "")),
                provider=f"Local Ollama ({chosen_model})",
            )
    except Exception as exc:
        logger.debug("Ollama scoring query failed: {}", exc)
    return None


# ──────────────────────────────────────────────────────────────────────
#  3. Google Gemini (Free Tier)
# ──────────────────────────────────────────────────────────────────────
async def score_with_gemini(
    job: dict[str, Any],
    profile: JobProfile,
    resume: dict[str, Any],
) -> Optional[ScoreBreakdown]:
    """Query Google Gemini API using free tier quota (if key present in .env)."""
    if not config.GEMINI_API_KEY:
        return None

    try:
        from google import genai
        client = genai.Client(api_key=config.GEMINI_API_KEY)

        prompt = (
            "You are an expert technical recruiter evaluating candidate fit.\n"
            "Evaluate this candidate against the job description.\n"
            "Respond ONLY with a valid JSON object:\n"
            "{\n"
            '  "total_score": <int 0-100>,\n'
            '  "skills_score": <int 0-40>,\n'
            '  "experience_score": <int 0-30>,\n'
            '  "domain_score": <int 0-20>,\n'
            '  "logistics_score": <int 0-10>,\n'
            '  "matched_skills": ["skill1", "skill2"],\n'
            '  "missing_skills": ["skillA"],\n'
            '  "pros": ["pro1", "pro2"],\n'
            '  "cons": ["con1"],\n'
            '  "reasoning": "1-2 sentence explanation"\n'
            "}\n\n"
            f"Target Profile: {profile.name}\n"
            f"Job Title: {job.get('title')}\n"
            f"Company: {job.get('company')}\n"
            f"Job Description:\n{str(job.get('description') or '')[:1800]}\n\n"
            f"Candidate Resume Data:\n{json.dumps(resume, ensure_ascii=False)[:1800]}"
        )

        loop = asyncio.get_event_loop()
        models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
        raw = ""
        for m in models:
            try:
                resp = await loop.run_in_executor(
                    None,
                    lambda: client.models.generate_content(model=m, contents=prompt),
                )
                raw = resp.text or ""
                if raw:
                    break
            except Exception:
                continue

        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        return ScoreBreakdown(
            total_score=max(0, min(100, int(data.get("total_score", 0)))),
            skills_score=max(0, min(40, int(data.get("skills_score", 0)))),
            experience_score=max(0, min(30, int(data.get("experience_score", 0)))),
            domain_score=max(0, min(20, int(data.get("domain_score", 0)))),
            logistics_score=max(0, min(10, int(data.get("logistics_score", 0)))),
            matched_skills=list(data.get("matched_skills", [])),
            missing_skills=list(data.get("missing_skills", [])),
            pros=list(data.get("pros", [])),
            cons=list(data.get("cons", [])),
            reasoning=str(data.get("reasoning", "")),
            provider="Google Gemini (Free Quota)",
        )
    except Exception as exc:
        logger.debug("Gemini scoring failed: {}", exc)
    return None


# ──────────────────────────────────────────────────────────────────────
#  Unified Entry Point
# ──────────────────────────────────────────────────────────────────────
async def calculate_transparent_score(
    job: dict[str, Any],
    profile: JobProfile,
    resume: dict[str, Any],
) -> ScoreBreakdown:
    """
    Computes a transparent score. Tries Ollama -> Gemini -> Local Deterministic fallback.
    Guarantees a complete ScoreBreakdown object.
    """
    # 1. Try Ollama (Local & Free)
    ollama_res = score_with_ollama(job, profile, resume)
    if ollama_res:
        return ollama_res

    # 2. Try Gemini (Free Quota) if API key provided
    gemini_res = await score_with_gemini(job, profile, resume)
    if gemini_res:
        return gemini_res

    # 3. Free Local Deterministic Matcher (Zero external dependencies)
    return score_deterministic(job, profile, resume)
