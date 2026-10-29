from pathlib import Path

import pytest

from claimcheck.llm import FakeLLM
from claimcheck.pdf_parser import parse_pdf
from claimcheck.reasoner import Reasoner, locate_quote
from claimcheck.store import Store

PDF = Path(__file__).resolve().parents[2] / "data" / "contracts" / "demo_habitation.pdf"
BIKE = "Je me fais voler mon vélo dans le local commun de l'immeuble, qui n'était pas fermé à clé. Suis-je couvert ?"
ANALYSIS = {"language": "fr", "perils": ["vol"], "topics": ["parties_communes", "velo"],
            "facts": ["vélo volé", "local commun non fermé à clé"], "unknowns": ["option vélo ?"],
            "search_terms": ["effraction", "parties communes", "local vélos"]}


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.ingest_pdf(PDF, "Démo")
    return s


def label_of(trace, ref):
    return next(r["label"] for r in trace if r["ref"] == ref)


def test_parser_keeps_structure():
    clauses, pages, _ = parse_pdf(PDF)
    refs = [c.ref for c in clauses]
    assert pages == 4
    assert "7.3" in refs and "10.2" in refs and "Lexique : Effraction" in refs
    assert not any("Page" in c.text and len(c.text) < 20 for c in clauses)  # footers removed
    c73 = next(c for c in clauses if c.ref == "7.3")
    assert "Vol et vandalisme" in c73.article and "fermé à clé" in c73.text


def test_tags_are_queryable(store):
    hits = store.compare("vol", "parties_communes", None)
    assert {"7.3", "7.4", "10.1"} <= {h["ref"] for h in hits}


def test_locate_quote_exact_fuzzy_and_reject():
    text = "Le contenu est couvert si le local était fermé à clé et si le vol a été commis avec effraction."
    assert locate_quote("si le local était fermé à clé", text)[2] == 1.0
    assert locate_quote("si le local etait ferme a cle et si le vol est commis", text) is not None
    assert locate_quote("les vélos sont toujours couverts partout", text) is None


def _decide_response(labels_7_3, label_7_4):
    return {
        "verdict": "non_couvert", "confidence": "haute", "summary": "Non couvert.",
        "reasoning": [{"step": "Le local commun doit être fermé à clé", "clause_ids": [labels_7_3]}],
        "citations": [
            {"clause_id": labels_7_3, "quote": "uniquement si le local était fermé à clé", "role": "condition"},
            {"clause_id": label_7_4, "quote": "les vols commis sans effraction ni violence dans les parties communes",
             "role": "exclusion"},
            {"clause_id": labels_7_3, "quote": "les vélos sont couverts partout sans condition", "role": "garantie"},
            {"clause_id": "C999", "quote": "clause inventée", "role": "garantie"},
        ],
        "missing_facts": ["L'option Vélo Tout Lieu est-elle souscrite ?"],
        "scenarios": [{"if": "option Vélo souscrite et antivol forcé", "then": "couvert", "clause_ids": []}],
        "limits": "Conditions particulières non fournies",
    }


def test_end_to_end_with_verification(store):
    r = Reasoner(store, None)
    retrieved = r.retrieve("demo", BIKE, ANALYSIS)
    labels = {c["ref"]: f"C{i + 1}" for i, c in enumerate(retrieved)}
    fake = FakeLLM([ANALYSIS, _decide_response(labels["7.3"], labels["7.4"])])
    out = Reasoner(store, fake).ask("demo", BIKE)
    assert out["verdict"] == "non_couvert"
    assert len(out["citations"]) == 2                     # two real quotes kept
    assert len(out["unverified_citations"]) == 2          # invented quote + unknown clause dropped
    assert out["warnings"]
    c = out["citations"][0]
    clause = store.clauses_by_ids([c["clause_id"]])[0]
    assert clause["text"][c["start"]:c["end"]] == c["quote"]  # offsets usable for highlighting
    assert out["trace"]["retrieved"] and out["trace"]["analysis"]["perils"] == ["vol"]


def test_firm_verdict_without_support_is_downgraded(store):
    fake = FakeLLM([ANALYSIS, {"verdict": "couvert", "confidence": "haute", "summary": "Oui",
                               "citations": [{"clause_id": "C1", "quote": "phrase qui n'existe pas du tout"}]}])
    out = Reasoner(store, fake).ask("demo", BIKE)
    assert out["verdict"] == "incertain"
    assert out["confidence"] != "haute"


def test_api(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMCHECK_DB", str(tmp_path / "api.db"))
    import importlib
    import claimcheck.api as api
    importlib.reload(api)
    from fastapi.testclient import TestClient
    client = TestClient(api.app)
    contracts = client.get("/api/contracts").json()
    assert contracts and contracts[0]["n_clauses"] > 40
    cid = contracts[0]["id"]
    assert len(client.get(f"/api/contracts/{cid}/clauses").json()) == contracts[0]["n_clauses"]
    api.reasoner.llm = FakeLLM([ANALYSIS, {"verdict": "incertain", "confidence": "moyenne", "summary": "Dépend.",
                                           "citations": [], "reasoning": []}])
    r = client.post("/api/ask", json={"contract_id": cid, "question": BIKE})
    assert r.status_code == 200 and r.json()["verdict"] == "incertain"
    assert client.get("/api/compare", params={"peril": "vol", "topic": "velo"}).json()
