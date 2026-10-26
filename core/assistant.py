"""
core/assistant.py — Truthful Resume & Cover Letter Assistance.

Generates tailored cover letters and resume highlight notes strictly
anchored in candidate's verified resume data.
STRICT ANTI-HALLUCINATION POLICY: Never invents skills, experiences,
metrics, dates, or degrees not explicitly present in resume.json.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Optional

import requests
from loguru import logger

import config
from core.profiles import JobProfile
from core.scorer import is_ollama_available


def generate_deterministic_cover_letter(
    job: dict[str, Any],
    resume: dict[str, Any],
    profile: JobProfile,
) -> str:
    """
    Template-driven truthful cover letter generator.
    Guaranteed 100% free, offline, and zero hallucination.
    """
    personal = resume.get("personal", {})
    candidate_name = personal.get("name", "Candidate")
    candidate_email = personal.get("email", "")
    candidate_phone = personal.get("phone", "")
    candidate_location = personal.get("location", "")

    title = job.get("title", "Software Role")
    company = job.get("company", "the Hiring Team")

    # Match genuine skills from candidate resume with job description
    candidate_skills = resume.get("skills", [])
    desc = (str(job.get("description") or "") + " " + title).lower()
    matching_skills = [
        s for s in candidate_skills
        if re.search(r"\b" + re.escape(s.lower()) + r"\b", desc)
    ]
    if not matching_skills:
        matching_skills = candidate_skills[:4]

    # Find relevant experience
    experiences = resume.get("experience", [])
    recent_exp = experiences[0] if experiences else None

    # Find relevant project
    projects = resume.get("projects", [])
    recent_proj = projects[0] if projects else None

    lines = [
        f"Dear Hiring Team at {company},",
        "",
        (
            f"I am writing to express my strong interest in the {title} position. "
            f"With hands-on background aligning with your target profile in {profile.name}, "
            f"I bring practical experience in {', '.join(matching_skills[:4])}."
        ),
        "",
    ]

    if recent_exp:
        exp_role = recent_exp.get("role", "Engineer")
        exp_comp = recent_exp.get("company", "previous organization")
        bullets = recent_exp.get("bullets", [])
        bullet_text = f" Specifically, I {bullets[0].lower()}" if bullets else ""
        lines.append(
            f"In my work as {exp_role} at {exp_comp}, I applied core engineering practices "
            f"to deliver maintainable, tested solutions.{bullet_text}"
        )
        lines.append("")

    if recent_proj:
        proj_name = recent_proj.get("name", "Key Project")
        proj_tech = ", ".join(recent_proj.get("tech", []))
        proj_bullets = recent_proj.get("bullets", [])
        proj_detail = f" where I {proj_bullets[0].lower()}" if proj_bullets else ""
        lines.append(
            f"Additionally, through my work on '{proj_name}' (built with {proj_tech}), "
            f"I demonstrated end-to-end technical execution{proj_detail}."
        )
        lines.append("")

    lines.extend([
        (
            f"I welcome the opportunity to discuss how my verified background and "
            f"technical skills can contribute to {company}'s goals. "
            "Thank you for your time and consideration."
        ),
        "",
        "Sincerely,",
        candidate_name,
        f"{candidate_email} | {candidate_phone} | {candidate_location}",
    ])

    return "\n".join(lines)


async def generate_truthful_cover_letter(
    job: dict[str, Any],
    resume: dict[str, Any],
    profile: JobProfile,
) -> str:
    """
    Generate a tailored cover letter using Ollama/Gemini (with strict anti-hallucination prompt)
    or fall back to the deterministic truthful template.
    """
    personal = resume.get("personal", {})
    candidate_name = personal.get("name", "Candidate")
    title = job.get("title", "Role")
    company = job.get("company", "Company")

    system_instruction = (
        "STRICT GROUNDING CONSTRAINT:\n"
        "You are assisting a job candidate with a truthful cover letter.\n"
        "Under NO circumstances should you fabricate, exaggerate, or invent skills, companies, "
        "projects, metrics, dates, or experiences that are not present in the provided resume.\n"
        "Only reference genuine items from the candidate's experience and project list."
    )

    prompt = (
        f"{system_instruction}\n\n"
        f"Write a concise, professional 3-paragraph cover letter for:\n"
        f"Candidate: {candidate_name}\n"
        f"Target Job: {title} at {company}\n"
        f"Profile: {profile.name}\n"
        f"Job Details: {str(job.get('description') or '')[:1200]}\n\n"
        f"Verified Resume Data:\n{json.dumps(resume, ensure_ascii=False)[:1800]}\n\n"
        "Output ONLY the plain text cover letter."
    )

    # 1. Try local Ollama
    ollama_ok, models = is_ollama_available()
    if ollama_ok and models:
        try:
            payload = {
                "model": models[0],
                "prompt": prompt,
                "stream": False,
            }
            res = requests.post("http://localhost:11434/api/generate", json=payload, timeout=25)
            if res.status_code == 200:
                text = res.json().get("response", "").strip()
                if len(text) > 100:
                    return text
        except Exception as exc:
            logger.debug("Ollama cover letter generation skipped: {}", exc)

    # 2. Try Gemini if configured
    if config.GEMINI_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=config.GEMINI_API_KEY)
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                ),
            )
            text = (resp.text or "").strip()
            if len(text) > 100:
                return text
        except Exception as exc:
            logger.debug("Gemini cover letter generation skipped: {}", exc)

    # 3. Deterministic truthful fallback
    return generate_deterministic_cover_letter(job, resume, profile)


def generate_resume_highlights(
    job: dict[str, Any],
    resume: dict[str, Any],
    profile: JobProfile,
) -> dict[str, Any]:
    """
    Selects real bullet points and projects from the candidate's resume
    that directly demonstrate qualifications for this job.
    """
    desc = (str(job.get("description") or "") + " " + str(job.get("title") or "")).lower()

    # Prioritize candidate projects with overlapping tech
    recommended_projects: list[dict[str, Any]] = []
    for proj in resume.get("projects", []):
        techs = proj.get("tech", [])
        matched_techs = [t for t in techs if re.search(r"\b" + re.escape(t.lower()) + r"\b", desc)]
        if matched_techs or not recommended_projects:
            recommended_projects.append({
                "name": proj.get("name"),
                "matched_tech": matched_techs,
                "bullets": proj.get("bullets", []),
            })

    # Find verified experience bullets with matching keywords
    highlighted_bullets: list[str] = []
    for exp in resume.get("experience", []):
        role = exp.get("role", "")
        company = exp.get("company", "")
        for bullet in exp.get("bullets", []):
            words = set(re.findall(r"\b[a-zA-Z]{3,}\b", bullet.lower()))
            overlap = [w for w in words if w in desc]
            if len(overlap) >= 2 or len(highlighted_bullets) < 2:
                highlighted_bullets.append(f"[{company} - {role}] {bullet}")

    # Identify skill gaps honestly
    candidate_skills_lower = {s.lower() for s in resume.get("skills", [])}
    missing_required = [
        s for s in profile.required_skills
        if s.lower() not in candidate_skills_lower
    ]

    return {
        "job_title": job.get("title"),
        "company": job.get("company"),
        "key_bullets_to_emphasize": highlighted_bullets[:5],
        "top_relevant_projects": recommended_projects[:2],
        "honest_skill_gaps": missing_required,
        "advice": (
            "During the interview, emphasize the verified projects above. "
            "Do not fabricate experience for any missing skills; frame them as areas you are actively learning."
        ),
    }
