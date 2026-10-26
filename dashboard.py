"""
dashboard.py — Streamlit Management Dashboard for AI Job Application Agent.

Features:
- Multi-profile filtering (Profile 1, 2, 3)
- Real-time KPIs (Discovered, Matched, Pending Review, Applied, Rejected)
- Review-Before-Submit approval workflow with manual apply links
- Transparent match score breakdowns (Skills, Experience, Domain, Logistics)
- Truthful cover letter & resume bullet recommendations
- Rejection analysis and filter transparency
- Application history and audit logs
- Interactive profile editor
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

import config
from core.assistant import (
    generate_deterministic_cover_letter,
    generate_resume_highlights,
    generate_truthful_cover_letter,
)
from core.db import (
    get_application_history,
    get_jobs_by_status,
    get_matched_jobs,
    get_pending_review_jobs,
    get_rejected_jobs,
    get_summary_metrics,
    init_db,
    save_assistant_notes,
    update_job_status,
)
from core.profiles import JobProfile, get_profile, load_profiles, save_profiles
from core.scorer import is_ollama_available

# Initialize DB schema
init_db()

# Page config
st.set_page_config(
    page_title="AI Job Agent — Review & Applications Dashboard",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 16px;
        border-left: 5px solid #2563eb;
    }
    .score-badge {
        font-size: 1.1rem;
        font-weight: 700;
        padding: 4px 10px;
        border-radius: 6px;
    }
    .score-high { background-color: #dcfce7; color: #166534; }
    .score-med { background-color: #fef9c3; color: #854d0e; }
    .score-low { background-color: #fee2e2; color: #991b1b; }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_candidate_resume() -> dict[str, Any]:
    try:
        return config.load_resume()
    except Exception:
        # Fallback to example if resume.json is not yet created
        ex = config.BASE_DIR / "resume.example.json"
        if ex.exists():
            with open(ex, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}


resume_data = load_candidate_resume()
profiles = load_profiles()
profile_map = {p.id: p for p in profiles}

# ── Sidebar ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("💼 AI Job Agent")
    st.caption("Review-Before-Submit Application Assistant")

    # System Status
    st.subheader("System Health")
    ollama_ok, ollama_models = is_ollama_available()
    if ollama_ok:
        st.success(f"🟢 Ollama Local LLM: Active ({', '.join(ollama_models[:2])})")
    else:
        st.info("⚪ Ollama Local LLM: Offline (using Free Rule Matcher)")

    if config.GEMINI_API_KEY:
        st.success("🟢 Google Gemini API: Key Configured")
    else:
        st.info("⚪ Gemini API: None (100% Free Local Mode)")

    st.markdown("---")
    st.subheader("Filter by Profile")
    profile_options = ["all"] + [p.id for p in profiles]
    selected_profile_id = st.selectbox(
        "Active Job Profile:",
        options=profile_options,
        format_func=lambda x: "All Profiles" if x == "all" else f"{x}: {profile_map[x].name}",
    )

    st.markdown("---")
    st.caption("Workflow Mode: **Review-Before-Submit (Default)**")
    st.caption("Database: `job_bot.db` (SQLite)")


# ── KPI Metrics ─────────────────────────────────────────────────────────
metrics = get_summary_metrics()
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Discovered", metrics["total_discovered"])
c2.metric("Matched", metrics["total_matched"])
c3.metric("Pending Review", metrics["pending_review"])
c4.metric("Approved", metrics["approved"])
c5.metric("Applied", metrics["total_applied"])
c6.metric("Rejected", metrics["total_rejected"])

st.markdown("---")

# ── Tabs ────────────────────────────────────────────────────────────────
tab_review, tab_matched, tab_rejected, tab_history, tab_profiles = st.tabs([
    "⏳ Review-Before-Submit Queue",
    "🌟 Matched Opportunities",
    "⛔ Rejected Jobs Log",
    "📜 Application Audit History",
    "⚙️ Job Profiles Configuration",
])

# ──────────────────────────────────────────────────────────────────────
#  Tab 1: Review-Before-Submit
# ──────────────────────────────────────────────────────────────────────
with tab_review:
    st.subheader("⏳ Pending Approval Queue")
    st.write(
        "Every discovered job that passes hard filters is placed here for your verification. "
        "Review match scores, check truthful cover letters, and approve or apply manually."
    )

    pending_jobs = get_pending_review_jobs(profile_id=selected_profile_id)

    if not pending_jobs:
        st.info("No jobs currently pending review. Run a search or scheduled task to discover new roles!")
    else:
        for job in pending_jobs:
            job_id = job["id"]
            score = job.get("ai_score", 0)
            score_class = "score-high" if score >= 75 else ("score-med" if score >= 60 else "score-low")

            breakdown_raw = job.get("score_breakdown")
            breakdown = json.loads(breakdown_raw) if breakdown_raw else {}

            with st.container():
                st.markdown(
                    f"""
                    <div style="border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 16px; background-color: #ffffff;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <h3 style="margin: 0; padding: 0;">{job.get('title', 'Unknown')}</h3>
                                <p style="margin: 4px 0; color: #4b5563; font-weight: 500;">
                                    🏢 <b>{job.get('company', 'Unknown')}</b> | 📍 {job.get('location', 'Not specified')} | 💵 {job.get('salary_raw') or 'Salary unlisted'}
                                </p>
                            </div>
                            <div>
                                <span class="score-badge {score_class}">Match Score: {score}/100</span>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                col_details, col_actions = st.columns([2, 1])

                with col_details:
                    # Dimensional Score Breakdown
                    if breakdown:
                        sc_skills = breakdown.get("skills_score", 0)
                        sc_exp = breakdown.get("experience_score", 0)
                        sc_dom = breakdown.get("domain_score", 0)
                        sc_log = breakdown.get("logistics_score", 0)
                        st.caption(
                            f"**Breakdown**: Skills: {sc_skills}/40 | Experience & Role: {sc_exp}/30 | "
                            f"Domain Fit: {sc_dom}/20 | Logistics: {sc_log}/10 (Provider: {breakdown.get('provider', 'Deterministic')})"
                        )

                        matched_skills = breakdown.get("matched_skills", [])
                        if matched_skills:
                            st.markdown(f"**Matched Skills:** {', '.join([f'`{s}`' for s in matched_skills])}")

                        missing_skills = breakdown.get("missing_skills", [])
                        if missing_skills:
                            st.markdown(f"**Missing Skills:** {', '.join([f'`{s}`' for s in missing_skills])}")

                        pros = breakdown.get("pros", [])
                        if pros:
                            st.markdown("**Pros:** " + "; ".join(pros))

                        cons = breakdown.get("cons", [])
                        if cons:
                            st.markdown("**Cons:** " + "; ".join(cons))

                    if job.get("description"):
                        with st.expander("📄 View Job Description"):
                            st.text(job["description"][:2500])

                with col_actions:
                    # Action Buttons
                    url = job.get("manual_apply_url") or job.get("url") or ""
                    if url:
                        st.link_button("🌐 Open Job Posting (Direct Link)", url, use_container_width=True)

                    btn_c1, btn_c2 = st.columns(2)
                    with btn_c1:
                        if st.button("✅ Approve", key=f"app_{job_id}", use_container_width=True):
                            update_job_status(job_id, "approved", notes="User approved via Dashboard")
                            st.success("Approved!")
                            st.rerun()

                    with btn_c2:
                        if st.button("❌ Dismiss", key=f"dis_{job_id}", use_container_width=True):
                            update_job_status(job_id, "skipped", notes="User dismissed via Dashboard")
                            st.info("Dismissed.")
                            st.rerun()

                    if st.button("💼 Mark Applied Manually", key=f"man_{job_id}", use_container_width=True):
                        update_job_status(job_id, "manual_applied", notes="Applied manually on external site")
                        st.success("Marked as Applied!")
                        st.rerun()

                    # Truthful Assistant Generator
                    with st.expander("📝 Generate Cover Letter & Highlights"):
                        p_obj = profile_map.get(job["profile_id"], profiles[0])
                        if st.button("Generate Truthful Materials", key=f"gen_{job_id}"):
                            letter = generate_deterministic_cover_letter(job, resume_data, p_obj)
                            highlights = generate_resume_highlights(job, resume_data, p_obj)
                            save_assistant_notes(job_id, cover_letter=letter, highlights=json.dumps(highlights))
                            st.rerun()

                        if job.get("tailored_cover_letter"):
                            st.text_area("Truthful Tailored Cover Letter:", job["tailored_cover_letter"], height=200)

                        if job.get("resume_highlights"):
                            try:
                                h_data = json.loads(job["resume_highlights"])
                                st.write("**Resume Bullets to Emphasize:**")
                                for b in h_data.get("key_bullets_to_emphasize", []):
                                    st.markdown(f"- {b}")
                            except Exception:
                                pass

                st.markdown("---")

# ──────────────────────────────────────────────────────────────────────
#  Tab 2: Matched Opportunities
# ──────────────────────────────────────────────────────────────────────
with tab_matched:
    st.subheader("🌟 All Matched Opportunities")
    matched_list = get_matched_jobs(profile_id=selected_profile_id)

    if not matched_list:
        st.info("No matched jobs found yet.")
    else:
        st.write(f"Total passing roles: **{len(matched_list)}**")
        for m in matched_list:
            score = m.get("ai_score", 0)
            status_label = m.get("status", "").upper()
            st.markdown(
                f"**{m.get('title')}** at *{m.get('company')}* | Score: `{score}/100` | Status: `{status_label}` | 📍 {m.get('location')}"
            )
            col_l, col_r = st.columns([4, 1])
            with col_l:
                if m.get("rejection_reason"):
                    st.caption(f"Note: {m.get('rejection_reason')}")
            with col_r:
                if m.get("manual_apply_url"):
                    st.link_button("View Listing", m.get("manual_apply_url"), use_container_width=True)
            st.divider()

# ──────────────────────────────────────────────────────────────────────
#  Tab 3: Rejected Jobs
# ──────────────────────────────────────────────────────────────────────
with tab_rejected:
    st.subheader("⛔ Filtered & Rejected Jobs")
    st.write("Inspect jobs that did not meet your hard constraints or minimum score criteria:")

    rejected_list = get_rejected_jobs(profile_id=selected_profile_id)
    if not rejected_list:
        st.success("No rejected jobs recorded.")
    else:
        for r in rejected_list:
            reason = r.get("rejection_reason") or "Below threshold"
            st.markdown(
                f"❌ **{r.get('title', 'Unknown')}** at *{r.get('company', 'Unknown')}* — Reason: `{reason}`"
            )
            st.caption(f"Location: {r.get('location', 'N/A')} | Salary: {r.get('salary_raw', 'N/A')} | Profile: {r.get('profile_name', 'N/A')}")
            st.divider()

# ──────────────────────────────────────────────────────────────────────
#  Tab 4: Application History
# ──────────────────────────────────────────────────────────────────────
with tab_history:
    st.subheader("📜 Application Audit Log")
    history_events = get_application_history(limit=150)
    if not history_events:
        st.info("No history events logged yet.")
    else:
        for ev in history_events:
            ts = ev.get("timestamp", "")
            action = ev.get("action", "").upper()
            title = ev.get("title", "Role")
            company = ev.get("company", "Company")
            notes = ev.get("notes", "")
            st.markdown(f"`{ts}` | **{action}** — {title} ({company}) {f'— *{notes}*' if notes else ''}")

# ──────────────────────────────────────────────────────────────────────
#  Tab 5: Profiles Configuration
# ──────────────────────────────────────────────────────────────────────
with tab_profiles:
    st.subheader("⚙️ Configure Your Three Job Profiles")
    st.write("Each profile independently defines target job titles, mandatory skills, salary requirements, and locations.")

    for idx, p in enumerate(profiles):
        with st.expander(f"Profile {idx + 1}: {p.name} ({p.id})", expanded=(idx == 0)):
            col1, col2 = st.columns(2)
            with col1:
                new_name = st.text_input("Profile Name", p.name, key=f"name_{p.id}")
                new_titles = st.text_area("Target Job Titles (one per line)", "\n".join(p.target_titles), key=f"titles_{p.id}")
                new_req_skills = st.text_area("Required Core Skills (one per line)", "\n".join(p.required_skills), key=f"req_skills_{p.id}")
                new_sec_skills = st.text_area("Secondary Skills (one per line)", "\n".join(p.secondary_skills), key=f"sec_skills_{p.id}")

            with col2:
                new_salary = st.number_input("Minimum Annual Salary", value=float(p.min_salary or 0), step=50000.0, key=f"sal_{p.id}")
                new_curr = st.selectbox("Currency", ["INR", "USD", "EUR", "GBP"], index=0 if p.currency == "INR" else 1, key=f"curr_{p.id}")
                new_locs = st.text_area("Preferred Locations (one per line)", "\n".join(p.preferred_locations), key=f"locs_{p.id}")
                new_loc_type = st.selectbox("Workplace Type", ["Any", "Remote", "Hybrid", "On-site"], index=0, key=f"loctype_{p.id}")
                new_min_exp = st.number_input("Min Experience (Years)", value=int(p.min_experience_years), key=f"minexp_{p.id}")
                new_max_exp = st.number_input("Max Experience (Years)", value=int(p.max_experience_years), key=f"maxexp_{p.id}")
                new_score = st.slider("Minimum Match Score (0–100)", 0, 100, int(p.min_match_score), key=f"score_{p.id}")

            if st.button("💾 Save Profile Changes", key=f"save_{p.id}"):
                p.name = new_name.strip()
                p.target_titles = [t.strip() for t in new_titles.split("\n") if t.strip()]
                p.required_skills = [s.strip() for s in new_req_skills.split("\n") if s.strip()]
                p.secondary_skills = [s.strip() for s in new_sec_skills.split("\n") if s.strip()]
                p.min_salary = new_salary
                p.currency = new_curr
                p.preferred_locations = [l.strip() for l in new_locs.split("\n") if l.strip()]
                p.location_type = new_loc_type
                p.min_experience_years = int(new_min_exp)
                p.max_experience_years = int(new_max_exp)
                p.min_match_score = int(new_score)
                save_profiles(profiles)
                st.success(f"Profile '{p.name}' updated and saved to profiles.json!")
                st.rerun()
