"""
core/ai_helper.py — Google Gemini API for job scoring + screening answers.

Get a free API key: https://aistudio.google.com/app/apikey
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from google import genai
from loguru import logger

import config

_client: genai.Client | None = None
_score_cache: dict[str, dict] = {}
_answer_cache: dict[str, str] = {}

# Prefer free-tier friendly models; fall back if one is quota-blocked
MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-2.0-flash",
)
_active_model: str | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY not set in .env. "
                "Get a free key at: https://aistudio.google.com/app/apikey"
            )
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _generate(prompt: str) -> str:
    """Call Gemini, sticky on the first working model."""
    global _active_model
    client = _get_client()
    models = ([_active_model] + [m for m in MODELS if m != _active_model]) if _active_model else list(MODELS)
    last_err: Exception | None = None
    for model in models:
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            _active_model = model
            return response.text or ""
        except Exception as exc:
            last_err = exc
            logger.debug("Model {} failed: {}", model, str(exc)[:120])
            continue
    raise last_err or RuntimeError("All Gemini models failed")


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if not text:
        raise ValueError("Empty AI response")
    return json.loads(text)


async def score_job(
    job_id: str,
    job_description: str,
    resume: dict[str, Any],
    job_title: str = "",
) -> dict[str, Any]:
    """Score resume–job fit 0–100. Returns {"score": int, "reasoning": str}."""
    if job_id in _score_cache:
        return _score_cache[job_id]

    # Lightweight heuristic when description is missing (common during scrape)
    if not (job_description or "").strip():
        prefs = resume.get("job_preferences", {})
        whitelist = [w.lower() for w in prefs.get("whitelist_keywords", [])]
        blacklist = [w.lower() for w in prefs.get("blacklist_keywords", [])]
        title_l = (job_title or "").lower()

        if any(b in title_l for b in blacklist):
            result = {"score": 20, "reasoning": "Title blacklist heuristic"}
            _score_cache[job_id] = result
            return result

        hits = sum(1 for w in whitelist if w in title_l)
        # Fresher-friendly base so single keyword matches (e.g. "software") clear typical thresholds
        score = min(92, 58 + hits * 10) if hits else 40

        # Soft penalty for clearly senior titles when candidate is fresher
        if any(x in title_l for x in ("senior", "lead", "principal", "staff", "5-8", "5+")):
            score = max(30, score - 15)

        # Soft boost for intern / fresher / junior / graduate
        if any(x in title_l for x in ("intern", "fresher", "junior", "graduate", "entry", "associate", "trainee")):
            score = min(95, score + 12)

        result = {
            "score": score,
            "reasoning": f"Title keyword heuristic ({hits} matches) — no full JD fetched",
        }
        _score_cache[job_id] = result
        return result

    try:
        prompt = (
            "You are an experienced technical recruiter evaluating resume-job fit. "
            "Score from 0-100 based on skills match, experience level, and requirements alignment. "
            "Respond with ONLY valid JSON: {\"score\": <int 0-100>, \"reasoning\": \"<1-2 sentences>\"}\n\n"
            f"Job Title: {job_title}\n\n"
            f"Job Description:\n{job_description[:2000]}\n\n"
            f"Candidate Resume:\n{json.dumps(resume, indent=2)[:2000]}"
        )

        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, lambda: _generate(prompt))

        result = _parse_json(raw)
        result["score"] = max(0, min(100, int(result.get("score", 0))))
        _score_cache[job_id] = result
        logger.info(
            "✓ Scored {} — Score: {} | {}",
            job_id,
            result["score"],
            str(result.get("reasoning", ""))[:60],
        )
        return result
    except Exception as exc:
        logger.warning("❌ Scoring failed for {}: {}", job_id, exc)
        return {"score": 0, "reasoning": f"Scoring error: {str(exc)[:50]}"}


async def answer_question(question_text: str, resume: dict[str, Any]) -> str:
    """Answer a screening question briefly using resume + screening_answers."""
    key = question_text.strip().lower()[:120]
    if key in _answer_cache:
        return _answer_cache[key]

    answers = resume.get("screening_answers", {})
    personal = resume.get("personal", {})

    try:
        prompt = (
            "Answer this job-application screening question as the candidate. "
            "Reply with ONLY the short answer text (no quotes, no explanation). "
            "Keep it under 40 words. Be honest and concise.\n\n"
            f"Question: {question_text}\n\n"
            f"Known answers: {json.dumps(answers)}\n"
            f"Personal: {json.dumps(personal)}\n"
            f"Skills: {json.dumps(resume.get('skills', [])[:20])}\n"
            f"Summary: {resume.get('summary', '')[:400]}"
        )
        loop = asyncio.get_event_loop()
        answer = (await loop.run_in_executor(None, lambda: _generate(prompt))).strip().strip('"').strip("'")
        if not answer:
            answer = str(answers.get("years_of_experience", "0"))
        _answer_cache[key] = answer
        return answer
    except Exception as exc:
        logger.debug("answer_question fallback: {}", exc)
        return str(answers.get("years_of_experience", "0"))


async def generate_cover_letter(
    job_id: str,
    job_title: str,
    company: str,
    job_description: str,
    resume: dict[str, Any],
) -> str:
    """Optional cover letter helper (unused by default apply flow)."""
    try:
        prompt = (
            "Write a short 3-paragraph cover letter. Plain text only.\n"
            f"Role: {job_title} at {company}\n"
            f"JD: {job_description[:1500]}\n"
            f"Resume: {json.dumps(resume)[:1500]}"
        )
        loop = asyncio.get_event_loop()
        return (await loop.run_in_executor(None, lambda: _generate(prompt))).strip()
    except Exception as exc:
        logger.warning("Cover letter failed: {}", exc)
        return ""
