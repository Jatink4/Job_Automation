"""Generate public/resume.pdf from resume.json (local profile only)."""

from __future__ import annotations

import json
from pathlib import Path

from fpdf import FPDF

import config


def main() -> None:
    resume_path = config.RESUME_JSON_PATH
    if not resume_path.exists():
        raise FileNotFoundError(
            f"{resume_path} not found. Copy resume.example.json to resume.json first."
        )

    with open(resume_path, encoding="utf-8") as fh:
        data = json.load(fh)

    personal = data.get("personal", {})
    name = personal.get("name", "Your Name")
    email = personal.get("email", "you@example.com")
    phone = personal.get("phone", "")
    location = personal.get("location", "")
    linkedin = personal.get("linkedin_url", "").replace("https://", "")
    github = personal.get("github_url", "").replace("https://", "")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.set_left_margin(14)
    pdf.set_right_margin(14)

    def p(text: str, bold: bool = False, size: float = 9.5) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.multi_cell(0, 4.6, text)

    def bullet(text: str) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 4.3, f"- {text}")

    def h1(text: str) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 16)
        pdf.multi_cell(0, 8, text)

    def h2(text: str) -> None:
        pdf.ln(3)
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(20, 60, 120)
        pdf.multi_cell(0, 7, text.upper())
        y = pdf.get_y()
        pdf.set_draw_color(20, 60, 120)
        pdf.line(14, y, 196, y)
        pdf.ln(2)
        pdf.set_text_color(0, 0, 0)

    h1(name.upper())
    contact = " | ".join(x for x in (location, phone, email) if x)
    if contact:
        p(contact)
    links = " | ".join(x for x in (linkedin, github) if x)
    if links:
        p(links)

    if data.get("summary"):
        h2("Professional Summary")
        p(data["summary"])

    if data.get("education"):
        h2("Education")
        for edu in data["education"]:
            p(
                f"{edu.get('degree', '')}, {edu.get('field', '')} | "
                f"{edu.get('start_date', '')} - {edu.get('end_date', '')}",
                bold=True,
            )
            p(
                f"{edu.get('institution', '')} | CGPA: {edu.get('cgpa', 'N/A')}"
            )

    if data.get("skills"):
        h2("Technical Skills")
        p(", ".join(data["skills"]))

    if data.get("experience"):
        h2("Experience")
        for exp in data["experience"]:
            p(
                f"{exp.get('role', '')} | {exp.get('company', '')} | "
                f"{exp.get('start_date', '')} - {exp.get('end_date', '')}",
                bold=True,
            )
            for item in exp.get("bullets", []):
                bullet(item)

    if data.get("projects"):
        h2("Projects")
        for proj in data["projects"]:
            tech = ", ".join(proj.get("tech", []))
            p(f"{proj.get('name', '')} | {proj.get('year', '')} | {tech}", bold=True)
            for item in proj.get("bullets", []):
                bullet(item)

    out = Path(__file__).resolve().parent.parent / "public" / "resume.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    print(f"Wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
