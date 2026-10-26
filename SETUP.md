# Setup

## Profile

Copy the example profile and add your own resume PDF:

```powershell
copy resume.example.json resume.json
copy your-resume.pdf public\resume.pdf
```

Edit `resume.json` with your name, contact info, skills, and job preferences.

## One-time

1. Gemini API key → `.env` as `GEMINI_API_KEY`  
   https://aistudio.google.com/app/apikey
2. (Optional) Telegram bot token + chat id in `.env`
3. Place your resume PDF at `public/resume.pdf` (or set `resume_pdf_path` in `resume.json`)

## Run

```powershell
cd "d:\Job bot"
.\.venv\Scripts\python main.py --sites linkedin --limit 15 --apply --max-apply 3
```

Log into LinkedIn in the browser window on first run.
