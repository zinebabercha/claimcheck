"""Evaluate ClaimCheck on a labelled set of claims.

  python eval/run_eval.py                      # full pipeline (needs MISTRAL_API_KEY)
  python eval/run_eval.py --retrieval-only     # no LLM: rule-based analysis + retrieval recall

Metrics
- verdict accuracy        : verdict is in the accepted set for the case
- over-confidence         : firm verdict (couvert / non_couvert) where the expected answer is the opposite firm verdict
- key-clause retrieval    : all key clauses were given to the model
- key-clause citation     : at least one key clause was cited with a verified quote
- unverified citations    : share of quotes rejected by the verification step (hallucination signal)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

from claimcheck.llm import MistralLLM  # noqa: E402
from claimcheck.reasoner import Reasoner  # noqa: E402
from claimcheck.store import Store  # noqa: E402


def main():
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(ROOT / "eval" / "cases_demo.json"))
    ap.add_argument("--pdf", default=str(ROOT / "data" / "contracts" / "demo_habitation.pdf"))
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--sleep", type=float, default=1.2, help="pause between cases (free-tier rate limit)")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    store = Store(ROOT / "eval" / "results" / "eval.db")
    contract = store.ingest_pdf(a.pdf, "eval")
    cid = contract["id"]
    cases = json.loads(Path(a.cases).read_text(encoding="utf-8"))
    if a.limit:
        cases = cases[: a.limit]
    llm = None if a.retrieval_only else MistralLLM()
    if llm is not None and not llm.configured:
        sys.exit("MISTRAL_API_KEY missing (or use --retrieval-only)")
    reasoner = Reasoner(store, llm)

    rows = []
    for case in cases:
        key = set(case["key_refs"])
        if a.retrieval_only:
            analysis = reasoner.analyse_rules(case["question"])
            got = reasoner.retrieve(cid, case["question"], analysis)
            refs = {c["ref"] for c in got}
            rows.append({"id": case["id"], "retrieval_ok": key <= refs, "missing": sorted(key - refs),
                         "n_retrieved": len(got)})
            continue
        t0 = time.time()
        try:
            out = reasoner.ask(cid, case["question"])
        except Exception as e:  # keep evaluating
            rows.append({"id": case["id"], "error": str(e)})
            continue
        retrieved = {r["ref"] for r in out["trace"]["retrieved"]}
        cited = {c["ref"] for c in out["citations"]}
        firm_wrong = (out["verdict"] in ("couvert", "non_couvert") and out["verdict"] not in case["expected"]
                      and "incertain" not in case["expected"])
        rows.append({
            "id": case["id"], "expected": case["expected"], "verdict": out["verdict"],
            "correct": out["verdict"] in case["expected"], "overconfident": firm_wrong,
            "retrieval_ok": key <= retrieved, "cited_key": (not key) or bool(key & cited),
            "n_cit": len(out["citations"]), "n_unverified": len(out["unverified_citations"]),
            "latency_s": round(time.time() - t0, 1), "summary": out["summary"],
        })
        print(f"{case['id']:28} {out['verdict']:12} {'OK ' if rows[-1]['correct'] else 'ERR'} "
              f"cited={sorted(cited)}")
        time.sleep(a.sleep)

    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(exist_ok=True)
    tag = "retrieval" if a.retrieval_only else os.getenv("MISTRAL_MODEL", "mistral-small-latest")
    (out_dir / f"results_{tag}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    n = len(rows)
    if a.retrieval_only:
        ok = sum(r["retrieval_ok"] for r in rows)
        print(f"\nKey-clause retrieval recall (rule-based analysis, no LLM): {ok}/{n} = {ok / n:.0%}")
        for r in rows:
            if not r["retrieval_ok"]:
                print("  missing", r["id"], r["missing"])
        return
    good = [r for r in rows if "error" not in r]
    m = len(good) or 1
    cit = sum(r["n_cit"] for r in good)
    unv = sum(r["n_unverified"] for r in good)
    report = [
        f"# ClaimCheck evaluation — {tag}", "",
        f"Cases: {n} (errors: {n - len(good)})", "",
        "| Metric | Value |", "|---|---|",
        f"| Verdict accuracy | {sum(r['correct'] for r in good)}/{len(good)} ({sum(r['correct'] for r in good) / m:.0%}) |",
        f"| Over-confident wrong verdicts | {sum(r['overconfident'] for r in good)} |",
        f"| Key clauses retrieved | {sum(r['retrieval_ok'] for r in good) / m:.0%} |",
        f"| Key clause cited (verified) | {sum(r['cited_key'] for r in good) / m:.0%} |",
        f"| Quotes rejected by verification | {unv}/{cit + unv} |",
        f"| Median latency | {sorted(r['latency_s'] for r in good)[len(good) // 2] if good else 0} s |", "",
        "| Case | Expected | Got | |", "|---|---|---|---|",
    ] + [f"| {r['id']} | {'/'.join(r.get('expected', []))} | {r.get('verdict', 'ERROR')} | "
         f"{'✅' if r.get('correct') else '❌'} |" for r in rows]
    (out_dir / f"report_{tag}.md").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report[:12]))


if __name__ == "__main__":
    main()
