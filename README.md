# Free AI Job Application Agent

> **Autonomous Job Discovery, Transparent Match Scoring & Review-Before-Submit Assistant**  
> *100% Free, Privacy-First, and Windows-Native*

---

## Overview

**Free AI Job Application Agent** is a desktop job-search automation engine that monitors career listings across **LinkedIn** and **Naukri**, compares them against your tailored **Job Profiles**, calculates an explainable **Match Score (0–100)**, and prepares truthful cover letters and application materials.

Unlike black-box auto-appliers that risk account bans or hallucinate qualifications, this agent operates on a **Review-Before-Submit** model by default. Every discovered match is staged in a local SQLite database and presented on a modern **Streamlit Dashboard** where you can inspect score breakdowns, review matched/missing skills, view direct application links, and approve or dismiss opportunities.

### Key Highlights

- **3 Configurable Job Profiles**: Pre-configured for three high-impact domains:
  1. 💻 **Software Engineer & Full Stack Developer** (C++, Python, React, Node.js, Express, MongoDB, FastAPI, RAG, AI Agents)
  2. 📊 **Data Analyst & Analytics Engineer** (Python, SQL, Pandas, NumPy, Power BI, EDA, Feature Engineering)
  3. 📈 **Strategy & Management Consulting / Business Analyst** (Business Strategy, Market Research, Financial Modeling, MECE, GTM Strategy, Excel)
- **Campus Placement & Fresher Targeted (0 Experience)**: Tailored for college graduates and freshers (`0 years experience`), with active anti-senior filters discarding 5+ year, 10+ year, lead, and director roles.
- **₹12+ LPA Salary Constraint**: Automatically filters out listings offering below **₹12,00,000 INR** (12 Lakhs / 12 LPA).
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
- **Truthful Assistant (No Hallucinations)**: Generates tailored cover letters and resume bullet recommendations anchored strictly in your verified resume data. Never invents qualifications, metrics, or degrees.
- **Per-Profile Resume Routing**: Automatically attaches the relevant resume PDF (`Tech_Resume.pdf`, `Data_Analystics.pdf`, or `Consulting_Resume.pdf`) to matching applications.
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
│  • Tech_Resume.pdf   • Data_Analystics.pdf   • Consulting_Resume.pdf   │
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
│  • Min Salary: > ₹12,00,000 INR (12 LPA) Check                         │
│  • Experience Bound: 0 Years (Fresher / Entry-Level)                   │
│  • Location & Remote Policy Match (India / Remote)                     │
│  • Work Auth / Sponsorship & Blacklisted Companies / Keywords          │
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

## The Three Configured Profiles

Profiles live in `profiles.json` (and can be edited visually in the Streamlit Dashboard under the **Job Profiles Configuration** tab).

### Profile 1: Software Engineer & Full Stack Developer
- **Target Titles:** `Software Engineer`, `Full Stack Developer`, `Backend Developer`, `Frontend Developer`, `SDE-1`, `SDE`, `Associate Software Engineer`, `Graduate Software Engineer`
- **Core Skills:** `Python`, `C++`, `JavaScript`, `React.js`, `Node.js`, `Express.js`, `MongoDB`, `REST APIs`, `SQL`
- **Secondary / AI Skills:** `FastAPI`, `Retrieval-Augmented Generation (RAG)`, `LLM`, `AI Agents`, `Firebase`, `Git`, `Render`, `Vercel`, `Pinecone`
- **Minimum Salary:** **₹12,00,000 INR (12 LPA)**
- **Locations:** Bangalore, Hyderabad, Pune, Gurgaon, Noida, Mumbai, Delhi NCR, Chennai, Remote, India
- **Experience Bound:** 0–1 Years (Fresher)
- **Resume PDF:** `public/Tech_Resume.pdf`

### Profile 2: Data Analyst & Analytics Engineer
- **Target Titles:** `Data Analyst`, `Junior Data Analyst`, `Analytics Engineer`, `Business Analyst - Data`, `Data Analytics Associate`, `Junior Data Scientist`, `Business Intelligence Analyst`, `BI Developer`, `Graduate Analyst`
- **Core Skills:** `Python`, `SQL`, `Pandas`, `NumPy`, `Power BI`, `Data Cleaning`, `Exploratory Data Analysis (EDA)`
- **Secondary Skills:** `Matplotlib`, `Seaborn`, `Microsoft Excel`, `Feature Engineering`, `Statistical Analysis`, `Dashboard Development`, `KPI Reporting`, `C++`
- **Minimum Salary:** **₹12,00,000 INR (12 LPA)**
- **Locations:** Bangalore, Gurgaon, Noida, Mumbai, Hyderabad, Pune, Delhi NCR, Remote, India
- **Experience Bound:** 0–1 Years (Fresher)
- **Resume PDF:** `public/Data_Analystics.pdf`

### Profile 3: Strategy & Management Consulting / Business Analyst
- **Target Titles:** `Management Consulting Associate`, `Consulting Analyst`, `Strategy Analyst`, `Business Analyst`, `Associate Consultant`, `Strategy & Operations Analyst`, `Corporate Strategy Associate`, `Graduate Consultant`, `Junior Consultant`
- **Core Skills:** `Business Strategy`, `Market Research`, `Financial Modeling`, `MECE`, `Root Cause Analysis`, `Power BI`, `Microsoft Excel`, `SQL`, `Python`
- **Secondary Skills:** `TAM/SAM/SOM`, `GTM Strategy`, `Pricing Strategy`, `SWOT Analysis`, `KPI Design`, `Stakeholder Management`, `Executive Presentation`
- **Minimum Salary:** **₹12,00,000 INR (12 LPA)**
- **Locations:** Gurgaon, Mumbai, Bangalore, Delhi NCR, Noida, Hyderabad, Pune, Remote, India
- **Experience Bound:** 0–1 Years (Fresher)
- **Resume PDF:** `public/Consulting_Resume.pdf`

---

## Installation on Windows

### Prerequisites

1. **Windows 10 or 11 (64-bit)**
2. **Python 3.11+** (Python 3.12, 3.13, or 3.15; verify with `python --version`)
3. **Google Chrome** or Playwright Chromium
4. *(Optional)* [Ollama](https://ollama.com) for 100% local AI matching

### 1. Set Up Virtual Environment

Open PowerShell in the project directory:

```powershell
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

### 3. Configure Credentials

Copy the provided example templates:

```powershell
copy .env.example .env
copy resume.example.json resume.json
copy profiles.example.json profiles.json
```

Add your optional Gemini API key or credentials to `.env`. Both `.env` and `resume.json` are excluded from Git via `.gitignore`.

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
- **Rejected Jobs Tab:** See why specific postings were filtered out (e.g. salary below ₹12 LPA or senior experience requirement).
- **Job Profiles Tab:** Modify skills, salary thresholds, and targets interactively.

### 2. Run Job Discovery (Dry-Run Mode)

Discover listings without submitting applications:

```powershell
# Discover jobs for all 3 profiles in safe dry-run mode
python main.py --profile all --dry-run

# Discover jobs specifically for Profile 1 (Tech)
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

The test suite covers:
- `tests/test_assistant.py` — Anti-hallucination verification for cover letters.
- `tests/test_db.py` — URL deduplication, canonical ID hashing, and state transitions.
- `tests/test_discovery.py` — End-to-end vetting and review staging.
- `tests/test_filters.py` — Salary parsing (LPA, hourly, annual), remote matching, sponsorship, and blacklists.
- `tests/test_profiles.py` — Multi-profile schema validation and loading.
- `tests/test_scorer.py` — 4-factor scoring breakdowns and pros/cons generation.

---

## Development Milestones & Commits

This project is organized into 10 structured, modular commits:

| Commit | Description |
| :--- | :--- |
| **`bcd421d`** | Initial project scaffold and MIT license attribution |
| **`c7eeea4`** | Add secure environment configuration and gitignore policies |
| **`a7f19ce`** | Implement 3 configurable job profiles architecture |
| **`dd7ee38`** | Implement strict hard filters and multi-currency salary parser |
| **`1c992cc`** | Add transparent 4-dimension match scoring engine with Ollama and Gemini support |
| **`dfb22ae`** | Add truthful assistant for tailored cover letters and resume highlights |
| **`3885a2e`** | Implement SQLite database layer with stable URL deduplication and review queue |
| **`9b49907`** | Build job discovery pipeline and Review-Before-Submit CLI workflow |
| **`982de84`** | Add Streamlit review dashboard with multi-profile inspection and manual apply links |
| **`cb334f6`** | Add comprehensive test suite, Windows scheduler scripts, and documentation |

---

## Attribution & License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

- Based upon the open-source architecture by **[Anuraga Muruganathan](https://github.com/AnuragaMuruganathan/job-bot)** and **[gurugsv7](https://github.com/gurugsv7/job-bot)**.
- Customized and extended with 3 configurable job profiles, transparent 4-dimension match scoring, local Ollama and offline evaluation, truthful cover-letter assistance, Windows Task Scheduler automation, and an interactive Streamlit review dashboard.
