"""PDF -> list of clauses.

Insurance general conditions are hierarchical documents (chapters > articles >
numbered sub-clauses, plus a lexicon). Instead of cutting them into fixed-size
chunks, we rebuild that hierarchy so every retrieved unit is one citable clause
with a stable reference ("7.3", "Art. 4", "Lexique : Effraction") and its pages.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

CHAPTER_RE = re.compile(r"^(chapitre|titre|partie|section)\s+([IVXLC]+|\d+)\b\s*[-–—:.]?\s*(.*)$", re.I)
ARTICLE_RE = re.compile(r"^(?:article|art\.)\s+(\d+[a-z]?(?:\.\d+)?)\b\s*[-–—:.]?\s*(.*)$", re.I)
NUMBERED_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){1,3})\.?\s+(\S.*)$")
LEXICON_HEAD_RE = re.compile(r"lexique|d[ée]finitions?|glossaire", re.I)
LEXICON_ENTRY_RE = re.compile(r"^([A-ZÀ-Ý][^:]{1,60}?)\s*:\s+(.+)$")
TOC_TAIL_RE = re.compile(r"(\.{3,}|…|\s{2,}|\t)\s*\d{1,3}\s*$|\s\d{1,3}$")


@dataclass
class Line:
    text: str
    page: int
    bold: bool
    y: float  # relative vertical position on page (0 top, 1 bottom)
    x: float = 0.0  # left position in points


@dataclass
class Clause:
    ref: str
    chapter: str
    article: str
    text: str
    page_start: int
    page_end: int
    is_lexicon: bool = False
    order: int = 0
    heading: str = ""
    parts: list[str] = field(default_factory=list)


def _norm_key(s: str) -> str:
    return re.sub(r"\d+", "#", s.strip().lower())


def extract_lines(pdf_path: str | Path) -> list[Line]:
    """Read text lines with position and boldness.

    Many insurer PDFs lay headings out in two pieces on the same baseline ("1.1." <tab> "Qui est assuré ?",
    "Article 1" <tab> "Personnes et biens assurés"); PyMuPDF returns them as separate lines. Pieces whose
    vertical position matches are merged back, left to right, into one logical line.
    """
    doc = pymupdf.open(pdf_path)
    out: list[Line] = []
    for pno, page in enumerate(doc, start=1):
        h = page.rect.height or 1
        raw = []
        for block in page.get_text("dict")["blocks"]:
            for ln in block.get("lines", []):
                spans = [s for s in ln["spans"] if s["text"].strip()]
                if not spans:
                    continue
                # spans already carry their own spaces; joining with " " would split words at style changes
                text = re.sub(r"\s+", " ", "".join(s["text"] for s in ln["spans"])).strip()
                bold = bool(spans[0]["flags"] & 16) or "bold" in spans[0]["font"].lower()
                raw.append([ln["bbox"][1], ln["bbox"][0], text, bold])
        raw.sort(key=lambda r: (round(r[0]), r[1]))
        merged: list[list] = []
        for y, x, text, bold in raw:
            if merged and abs(merged[-1][0] - y) < 2.5 and x > merged[-1][1]:
                merged[-1][2] += " " + text
                merged[-1][4] = max(merged[-1][4], x)
            else:
                merged.append([y, x, text, bold, x])
        for y, x, text, bold, _ in merged:
            out.append(Line(text, pno, bold, y / h, x))
    doc.close()
    return out


def drop_running_headers(lines: list[Line]) -> list[Line]:
    """Remove page headers/footers: short lines repeated on many pages near the edges."""
    pages = {l.page for l in lines}
    if len(pages) < 3:
        edge = [l for l in lines if l.y < 0.08 or l.y > 0.92]
    else:
        edge = lines
    counts = Counter(_norm_key(l.text) for l in edge if (l.y < 0.1 or l.y > 0.9))
    threshold = max(2, int(0.5 * len(pages)))
    repeated = {k for k, c in counts.items() if c >= threshold}
    kept = []
    for l in lines:
        k = _norm_key(l.text)
        if (l.y < 0.1 or l.y > 0.9) and (k in repeated or re.fullmatch(r"(page\s*)?#(\s*/\s*#)?", k)):
            continue
        kept.append(l)
    return kept


def _toc_candidate(line: Line) -> bool:
    t = line.text
    is_heading = CHAPTER_RE.match(t) or ARTICLE_RE.match(t) or NUMBERED_RE.match(t)
    return bool(is_heading and len(t) < 140 and re.search(r"(\.{3,}|…|\s)\s*\d{1,3}$", t))


def drop_toc(lines: list[Line]) -> list[Line]:
    """Remove the table of contents: pages where many heading lines end with a page number."""
    per_page = Counter(l.page for l in lines if _toc_candidate(l))
    toc_pages = {p for p, n in per_page.items() if n >= 5}
    return [l for l in lines if not (l.page in toc_pages and _toc_candidate(l))]


def _join(parts: list[str]) -> str:
    text = ""
    for p in parts:
        if text.endswith("-") and p[:1].islower():
            text = text[:-1] + p
        elif text:
            text += " " + p
        else:
            text = p
    return re.sub(r"\s+", " ", text).strip()


def parse_clauses(lines: list[Line]) -> list[Clause]:
    lines = drop_running_headers(lines)
    lines = drop_toc(lines)

    clauses: list[Clause] = []
    chapter, article = "", ""
    in_lexicon = False
    cur: Clause | None = None
    n_head = 0  # number of heading parts at the start of cur.parts (content starts after them)

    def close():
        nonlocal cur
        if cur and (cur.parts or cur.heading):
            cur.text = _join(cur.parts) or cur.heading
            # numbered clauses are kept even when they are only a title ("3.1. L'incendie" lists a guarantee)
            if len(cur.text) >= (3 if re.match(r"^\d", cur.ref) else 15):
                cur.order = len(clauses)
                clauses.append(cur)
        cur = None

    def start(**kw):
        nonlocal cur, n_head
        close()
        cur = Clause(text="", page_start=kw.pop("page"), page_end=kw.pop("page_end"), **kw)
        n_head = len(cur.parts)

    for l in lines:
        t = l.text
        m_ch, m_ar, m_num = CHAPTER_RE.match(t), ARTICLE_RE.match(t), NUMBERED_RE.match(t)
        if m_ch and len(t) < 120:
            close()
            chapter, article = t, ""
            in_lexicon = bool(LEXICON_HEAD_RE.search(t))
            continue
        if not m_ar and len(t) < 60 and l.bold and LEXICON_HEAD_RE.fullmatch(t.strip(" :")):
            close()
            chapter, article = t, ""
            in_lexicon = True
            continue
        if m_ar and len(t) < 140:
            article = t
            in_lexicon = bool(LEXICON_HEAD_RE.search(t)) or bool(LEXICON_HEAD_RE.search(chapter))
            start(ref=f"Art. {m_ar.group(1)}", chapter=chapter, article=article, heading=t,
                  page=l.page, page_end=l.page)
            continue
        if m_num and not in_lexicon:
            start(ref=m_num.group(1), chapter=chapter, article=article, parts=[m_num.group(2)],
                  page=l.page, page_end=l.page)
            continue
        if in_lexicon:
            m_lex = LEXICON_ENTRY_RE.match(t)
            if m_lex and (l.bold or len(m_lex.group(1).split()) <= 6):  # "Terme : définition"
                start(ref=f"Lexique : {m_lex.group(1).strip()}", chapter=chapter, article=article or chapter,
                      is_lexicon=True, parts=[t], page=l.page, page_end=l.page)
                n_head = 0
                continue
            if l.bold and len(t) < 80 and not t.rstrip().endswith((".", ";", ",")):  # term alone, definition below
                term = t.strip(" :")
                start(ref=f"Lexique : {term}", chapter=chapter, article=article or chapter,
                      is_lexicon=True, parts=[f"{term} :"], page=l.page, page_end=l.page)
                continue
        elif (cur is not None and l.bold and len(t) < 100 and len(cur.parts) > n_head
              and (t[:1].isupper() or t[:1].isdigit()) and re.search(r"[.:;?!»)]$", cur.parts[-1].strip())):
            # bold sub-heading inside a clause ("Nous indemnisons également", "Obligations de prévention"):
            # start a sub-clause so that exclusions, extensions and obligations are retrieved separately
            base = cur.ref.split(" · ")[0]
            if not base.endswith("(intro)"):
                start(ref=f"{base} · {t.strip(' :')[:45]}", chapter=chapter, article=article, parts=[t],
                      page=l.page, page_end=l.page)
                continue
        if cur is None:
            if not chapter and not article:
                continue  # preamble / cover page
            start(ref=f"{(article or chapter)[:40]} (intro)", chapter=chapter, article=article,
                  page=l.page, page_end=l.page)
        cur.parts.append(t)
        cur.page_end = l.page
    close()

    # an article heading immediately followed by numbered sub-clauses carries no own text: drop empties
    clauses = [c for c in clauses if c.text and c.text != c.heading]
    for i, c in enumerate(clauses):
        c.order = i
    return clauses


def parse_pdf(pdf_path: str | Path) -> tuple[list[Clause], int, str]:
    lines = extract_lines(pdf_path)
    pages = max((l.page for l in lines), default=0)
    title = next((l.text for l in lines[:12] if len(l.text) > 15 and l.y > 0.08), Path(pdf_path).stem)
    return parse_clauses(lines), pages, title
