"""Render the synthetic demo policy (data/source/demo_policy.txt) into a PDF.

The PDF imitates a real insurer document (running header/footer, bold headings)
so the ingestion pipeline is exercised exactly as on a real policy.
"""
from pathlib import Path
import re
import sys

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "source" / "demo_policy.txt"
OUT = ROOT / "data" / "contracts" / "demo_habitation.pdf"

body = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13, spaceAfter=4)
h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=12, leading=16, spaceBefore=10, spaceAfter=6)
h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceBefore=6, spaceAfter=3)
title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=15, leading=20, spaceAfter=8)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(2 * cm, A4[1] - 1.2 * cm, "Démo Assurances – Assurance Habitation – CG v1.0 (document synthétique)")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.restoreState()


def main(src: Path = SRC, out: Path = OUT) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = src.read_text(encoding="utf-8").splitlines()
    story = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        if i < 2:
            story.append(Paragraph(esc(line), title))
        elif line.startswith("CHAPITRE"):
            story.append(Paragraph(esc(line), h1))
        elif line.startswith("Article"):
            story.append(Paragraph(esc(line), h2))
        else:
            m = re.match(r"^([A-ZÉ][\wéèêàâîôûç' ]{2,40}) : (.*)$", line)
            if m:  # lexicon entry: bold term
                story.append(Paragraph(f"<b>{esc(m.group(1))}</b> : {esc(m.group(2))}", body))
            else:
                story.append(Paragraph(esc(line), body))
        story.append(Spacer(1, 1))
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm,
                            title="Conditions générales Assurance Habitation (synthétique)")
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(*(Path(a) for a in sys.argv[1:]))
