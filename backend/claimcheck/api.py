"""FastAPI app: contracts, clauses, ask, structured compare, upload. Serves the React build in production."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .llm import LLMError, MistralLLM
from .reasoner import Reasoner
from .store import Store
from .tagging import PERILS, TOPICS

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DB_PATH = os.getenv("CLAIMCHECK_DB", str(ROOT / "data" / "claimcheck.db"))
CONTRACTS_DIR = Path(os.getenv("CLAIMCHECK_CONTRACTS", str(ROOT / "data" / "contracts")))
FRONTEND_DIST = Path(os.getenv("CLAIMCHECK_FRONTEND", str(ROOT / "frontend" / "dist")))
ALLOW_UPLOAD = os.getenv("CLAIMCHECK_ALLOW_UPLOAD", "1") == "1"

EXAMPLES = [
    "Je me fais voler mon vélo dans le local commun de l'immeuble, qui n'était pas fermé à clé. Suis-je couvert ?",
    "Un assuré laisse une bougie sur la table de son jardin pendant ses vacances. Avec la chaleur, la bougie fond "
    "et abîme la table. Est-ce couvert ?",
    "Une fuite sous mon évier a abîmé le parquet de la cuisine. Suis-je couvert ?",
    "My bike was stolen from my locked private garage; the door was forced. Am I covered?",
]

store = Store(DB_PATH)
llm = MistralLLM()
reasoner = Reasoner(store, llm)


def bootstrap() -> None:
    """Ingest every PDF in data/contracts/ that is not in the database yet."""
    known = {c["source_file"] for c in store.list_contracts()}
    for pdf in sorted(CONTRACTS_DIR.glob("*.pdf")):
        if pdf.name not in known:
            try:
                store.ingest_pdf(pdf, pdf.stem.replace("_", " ").title())
            except Exception as e:  # keep the app up even if one file is bad
                print(f"[ingest] {pdf.name}: {e}")


bootstrap()

app = FastAPI(title="ClaimCheck", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class AskIn(BaseModel):
    contract_id: str
    question: str = Field(min_length=10, max_length=2000)


@app.get("/api/health")
def health():
    return {"ok": True, "llm_configured": llm.configured, "model": llm.model, "upload": ALLOW_UPLOAD}


@app.get("/api/meta")
def meta():
    return {"examples": EXAMPLES, "perils": list(PERILS), "topics": list(TOPICS)}


@app.get("/api/contracts")
def contracts():
    return store.list_contracts()


@app.get("/api/contracts/{cid}/clauses")
def clauses(cid: str):
    if not store.get_contract(cid):
        raise HTTPException(404, "Contrat inconnu")
    return store.clauses(cid)


@app.get("/api/contracts/{cid}/pdf")
def contract_pdf(cid: str):
    c = store.get_contract(cid)
    if not c or not (CONTRACTS_DIR / c["source_file"]).exists():
        raise HTTPException(404, "PDF introuvable")
    return FileResponse(CONTRACTS_DIR / c["source_file"], media_type="application/pdf")


@app.post("/api/ask")
def ask(body: AskIn):
    if not store.get_contract(body.contract_id):
        raise HTTPException(404, "Contrat inconnu")
    try:
        return reasoner.ask(body.contract_id, body.question)
    except LLMError as e:
        raise HTTPException(503, str(e))


@app.get("/api/compare")
def compare(peril: str | None = None, topic: str | None = None, type: str | None = None):
    rows = store.compare(peril, topic, type)
    names = {c["id"]: c["name"] for c in store.list_contracts()}
    grouped: dict[str, dict] = {}
    for r in rows:
        g = grouped.setdefault(r["contract_id"], {"contract_id": r["contract_id"],
                                                   "name": names.get(r["contract_id"], r["contract_id"]),
                                                   "clauses": []})
        g["clauses"].append(r)
    return list(grouped.values())


@app.post("/api/contracts")
def upload(file: UploadFile = File(...), name: str = Form(...), use_llm: bool = Form(False)):
    if not ALLOW_UPLOAD:
        raise HTTPException(403, "Téléversement désactivé sur cette instance")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Seuls les PDF sont acceptés")
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        if tmp.tell() > 25 * 1024 * 1024:
            raise HTTPException(413, "PDF trop volumineux (25 Mo max)")
    dest = CONTRACTS_DIR / (Path(file.filename).stem.replace(" ", "_")[:60] + ".pdf")
    shutil.move(tmp.name, dest)
    try:
        return store.ingest_pdf(dest, name, llm=llm if (use_llm and llm.configured) else None)
    except ValueError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, str(e))


# ---- serve the React build (single container deployment)
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = FRONTEND_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
