# Free AI Job Application Agent

> **Autonomous Job Discovery, Transparent Match Scoring & Review-Before-Submit Assistant**  
> *100% Free, Privacy-First, and Windows-Native*

---

## Overview

**Free AI Job Application Agent** is a desktop job-search automation engine that monitors career listings across **LinkedIn** and **Naukri**, compares them against your tailored **Job Profiles**, calculates an explainable **Match Score (0–100)**, and prepares truthful cover letters and application materials.

Unlike black-box auto-appliers that risk account bans or hallucinate qualifications, this agent operates on a **Review-Before-Submit** model by default. Every discovered match is staged in a local SQLite database and presented on a modern **Streamlit Dashboard** where you can inspect score breakdowns, review matched/missing skills, view direct application links, and approve or dismiss opportunities.

### Key Highlights

- **3 Configurable Job Profiles**: Target separate roles (e.g., Full Stack Engineer, Data & ML Engineer, DevOps & Cloud Engineer) with individual title lists, skill criteria, minimum salary bounds, and location rules.
- **Strict Hard Filters**: Discard listings instantly if they fail minimum salary requirements, location/remote policy, visa sponsorship constraints, experience ceilings, or company/keyword blacklists.
- **Transparent Match Scoring**: Decomposes fit into 4 dimensions:
  - 🛠️ **Skills Alignment (0–40 pts)**
  - 💼 **Experience & Title Fit (0–30 pts)**
  - 🎯 **Domain & Project Relevance (0–20 pts)**
  - 📍 **Logistics & Preferences (0–10 pts)**
- **100% Free & Local AI Matching**:
  - Run offline with **Local Ollama** (`llama3.2`, `mistral`, `qwen2.5`).
  - Optional **Google Gemini** free quota tier (60 req/min, $0 cost).
  - Built-in **Free Local Deterministic Matcher** requiring **zero API keys** or accounts!
- **Truthful Assistant (No Hallucinations)**: Generates tailored cover letters and resume bullet recommendations anchored strictly in your verified `resume.json`. Never invents qualifications, metrics, or degrees.
- **Stable URL Deduplication**: Remembers every discovered job across sessions using canonical URL hashing so you never see or apply to duplicates.
- **Interactive Web Dashboard**: Streamlit-based UI to review pending jobs, inspect score breakdowns, filter by profile, view rejection diagnostics, and manage history.
- **Windows Task Scheduler Integration**: Run automated discovery every morning (e.g. 9:00 AM) in dry-run mode so your review queue is fresh when you wake up.
- **Compliance & Anti-Ban Safety**: Respectful human-simulated jitter delays. Does not attempt to crack CAPTCHAs, evade anti-bot security, or violate platform terms.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        CANDIDATE CONFIGURATION                         │
│  resume.json (Experience & Projects)  +  profiles.json (3 Job Profiles)│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         JOB DISCOVERY PIPELINE                         │
│  Playwright Browser / Search Scrapers (LinkedIn, Naukri)                │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                          STRICT HARD FILTERS                           │
│  • Min Salary Threshold Check   • Location & Remote Policy Match       │
│  • Work Auth / Sponsorship      • Blacklisted Companies & Keywords     │
└───────────────────┬────────────────────────────────┬───────────────────┘
                    │ (Passed)                       │ (Failed)
                    ▼                                ▼
┌──────────────────────────────────────┐  ┌──────────────────────────────┐
│       TRANSPARENT MATCH SCORER       │  │        REJECTED JOBS         │
│  • Skills Alignment        (0-40)    │  │  Logged to DB with exact     │
│  • Experience & Seniority  (0-30)    │  │  rejection explanation       │
│  • Domain & Projects Fit   (0-20)    │  └──────────────────────────────┘
│  • Logistics & Preferences (0-10)    │
│  Backends: Ollama | Gemini | Offline │
└───────────────────┬──────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       LOCAL SQLITE DATABASE (job_bot.db)               │
│  • Deduplication via Canonical URL Hash                                │
│  • Multi-Profile Workflow Tracking                                     │
└───────────────────┬────────────────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 REVIEW-BEFORE-SUBMIT WEB DASHBOARD                     │
│  (python -m streamlit run dashboard.py)                                │
│  • Inspect Score Breakdown & Pros/Cons                                 │
│  • Click Direct Manual Apply Link                                      │
│  • Generate Truthful Tailored Cover Letter                             │
│  • Approve for Auto-Submit or Mark Applied Manually                    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Installation on Windows

### Prerequisites

1. **Windows 10 or 11 (64-bit)**
2. **Python 3.11+** (Python 3.12 or 3.13 recommended; verify with `python --version`)
3. **Google Chrome** or Playwright Chromium
4. *(Optional)* [Ollama](https://ollama.com) for 100% local AI matching

### 1. Set Up Virtual Environment

Open PowerShell in the project directory:

```powershell
# Navigate to the project root
cd "D:\project upload to github\Job_Automation"

# Create a clean virtual environment
python -m venv .venv

# Activate the virtual environment
.\.venv\Scripts\Activate.ps1
```

> **Note for PowerShell execution policies:** If script execution is restricted, run:  
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

### 2. Install Dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

### 3. Initialize Configuration Files

Copy the provided example templates:

```powershell
copy .env.example .env
copy resume.example.json resume.json
copy profiles.example.json profiles.json
```

---

## Configuring Your Three Job Profiles

Profiles live in `profiles.json` (and can be edited visually in the Streamlit Dashboard under the **Job Profiles Configuration** tab).

### Profile 1: Full Stack & Python Developer
- **Target Titles:** Software Engineer, Full Stack Developer, Python Developer, Backend Engineer
- **Required Skills:** `["Python", "FastAPI", "React", "SQL", "Git"]`
- **Secondary Skills:** `["TypeScript", "Docker", "REST APIs", "PostgreSQL"]`
- **Minimum Salary:** 600,000 INR (~6 LPA) or customizable
- **Locations:** Bangalore, Hyderabad, Pune, Remote (Any workplace type)
- **Experience Bound:** 0–3 Years

### Profile 2: Data Engineer & Machine Learning
- **Target Titles:** Data Engineer, Machine Learning Engineer, AI Engineer, Python Data Developer
- **Required Skills:** `["Python", "Pandas", "SQL", "Machine Learning", "PyTorch"]`
- **Secondary Skills:** `["Docker", "FastAPI", "Scikit-Learn", "ETL", "Spark"]`
- **Minimum Salary:** 700,000 INR (~7 LPA)
- **Locations:** Bangalore, Gurgaon, Mumbai, Remote
- **Experience Bound:** 0–3 Years

### Profile 3: DevOps & Cloud Engineer
- **Target Titles:** DevOps Engineer, Cloud Engineer, Site Reliability Engineer, Platform Engineer
- **Required Skills:** `["AWS", "Docker", "Linux", "CI/CD", "Python"]`
- **Secondary Skills:** `["Kubernetes", "Terraform", "GitHub Actions", "Bash"]`
- **Minimum Salary:** 650,000 INR (~6.5 LPA)
- **Locations:** Bangalore, Hyderabad, Noida, Remote
- **Experience Bound:** 0–3 Years

---

## Usage Guide

### 1. Launch the Review Dashboard

The dashboard is your central cockpit for vetting opportunities and managing applications:

```powershell
python -m streamlit run dashboard.py
```

The web dashboard opens at `http://localhost:8501`:
- **Pending Review Tab:** See all matches with transparent scores, pros/cons, direct manual apply links, and approve buttons.
- **Generate Cover Letter:** Creates truthful application letters tailored to the posting without fabricating experience.
- **Rejected Jobs Tab:** See why specific postings were filtered out.
- **Job Profiles Tab:** Modify skills, salary thresholds, and targets interactively.

### 2. Run Job Discovery (Dry-Run Mode)

Discover listings without submitting applications:

```powershell
# Discover jobs for all 3 profiles in safe dry-run mode
python main.py --profile all --dry-run

# Discover jobs specifically for Profile 1
python main.py --profile profile_1 --dry-run --limit 15
```

### 3. Review-Before-Submit Flow

1. The bot discovers listings and runs them through hard filters and scoring.
2. Passing jobs enter the `review_pending` queue in `job_bot.db`.
3. Open `dashboard.py` to inspect each job.
4. For roles you like:
   - Click **Open Job Posting** to apply directly in your browser, then click **Mark Applied Manually**.
   - Or click **Approve** to stage for one-click submission.

---

## Setting Up Daily Scheduled Searches

Automate daily discovery using **Windows Task Scheduler**. Scheduled jobs run quietly in `--dry-run` mode so they never submit applications without your permission.

### Method A: One-Click PowerShell Script

```powershell
# Schedule daily discovery at 09:00 AM
.\scripts\schedule_task.ps1 -Time "09:00"

# Run the task immediately to test
Start-ScheduledTask -TaskName "AI_Job_Bot_Daily_Discovery"

# Remove the scheduled task later
.\scripts\schedule_task.ps1 -Uninstall
```

### Method B: One-Click Batch Script

Right-click `scripts\setup_scheduled_task.bat` and select **Run as Administrator**.

---

## Running the Automated Test Suite

Verify all filters, scoring components, deduplication logic, and anti-hallucination policies:

```powershell
pytest
```

The suite covers:
- `tests/test_profiles.py` — Multi-profile schema validation and loading.
- `tests/test_filters.py` — Salary parsing (LPA, hourly, annual), remote matching, sponsorship, and blacklists.
- `tests/test_scorer.py` — 4-factor scoring breakdowns and pros/cons generation.
- `tests/test_db.py` — URL deduplication, canonical ID hashing, and state transitions.
- `tests/test_assistant.py` — Anti-hallucination verification for cover letters.
- `tests/test_discovery.py` — End-to-end vetting and review staging.

---

## Troubleshooting & Safety

| Symptom | Cause | Solution |
| :--- | :--- | :--- |
| **LinkedIn asks for login on first run** | Persistent session not yet saved | On your first run, a visible browser window opens. Log in once manually. Your session is saved in `browser_data/` and will not prompt again. |
| **No API Key configured** | `GEMINI_API_KEY` is empty in `.env` | Not an error! The system automatically uses the **Free Local Deterministic Matcher** (0 cost, no key required) or Local Ollama. |
| **Ollama connection refused** | Ollama is not running | If using Ollama, start the Ollama desktop app or run `ollama serve`. If not using Ollama, the agent falls back to deterministic matching. |
| **Job listings fail with CAPTCHA** | LinkedIn triggered a security verification | The bot **does not** bypass CAPTCHAs to protect your account from bans. Simply complete the verification manually in the browser window. |
| **Execution Policy Error in PowerShell** | Windows script execution policy | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in your terminal. |

---

## Ethical Automation & Terms Compliance

1. **No CAPTCHA Bypass:** This application adheres to web security protocols and does not attempt to circumvent CAPTCHAs, Cloudflare checks, or bot detection puzzles.
2. **Review-Before-Submit:** Applications are never submitted blindly. You retain full control over which companies receive your resume.
3. **Truth in Advertising:** Cover letters and screening responses are grounded strictly in your genuine resume data.

---

## Attribution & License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

- Based upon the open-source architecture by **[Anuraga Muruganathan](https://github.com/AnuragaMuruganathan/job-bot)** and **[gurugsv7](https://github.com/gurugsv7/job-bot)**.
- Customized and extended with 3 configurable job profiles, transparent 4-dimension match scoring, local Ollama and offline evaluation, truthful cover-letter assistance, Windows Task Scheduler automation, and an interactive Streamlit review dashboard.
