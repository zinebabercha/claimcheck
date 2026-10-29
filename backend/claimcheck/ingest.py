"""CLI: python -m claimcheck.ingest path/to/policy.pdf --name "Ethias Habitation" [--llm]"""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from .llm import MistralLLM
from .store import Store

ROOT = Path(__file__).resolve().parents[2]


def main():
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--name")
    ap.add_argument("--llm", action="store_true", help="refine clause tags with Mistral")
    ap.add_argument("--db", default=os.getenv("CLAIMCHECK_DB", str(ROOT / "data" / "claimcheck.db")))
    a = ap.parse_args()
    store = Store(a.db)
    c = store.ingest_pdf(a.pdf, a.name, llm=MistralLLM() if a.llm else None)
    print(f"{c['name']}: {c['n_clauses']} clauses, {c['pages']} pages (tagger={c['tagger']})")
    for cl in store.clauses(c["id"])[:400]:
        print(f"  {cl['ref'][:28]:28} p.{cl['page_start']:<3} {','.join(cl['types']):24} "
              f"{','.join(cl['perils']):20} {cl['text'][:70]}")


if __name__ == "__main__":
    main()
