"""SQLite storage: contracts, clauses, clause tags (for structured SQL queries), and a full-text index.

One row per clause, one row per tag. That makes "which contracts cover bikes stolen
from a shared storage room?" a SQL query across all contracts instead of a prompt.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from .pdf_parser import parse_pdf
from .tagging import dumps, tag_rules, tag_with_llm

SCHEMA = """
CREATE TABLE IF NOT EXISTS contracts (
  id TEXT PRIMARY KEY, name TEXT, title TEXT, source_file TEXT, pages INT,
  n_clauses INT, tagger TEXT, ingested_at REAL
);
CREATE TABLE IF NOT EXISTS clauses (
  id TEXT PRIMARY KEY, contract_id TEXT REFERENCES contracts(id) ON DELETE CASCADE,
  ord INT, ref TEXT, chapter TEXT, article TEXT, text TEXT,
  page_start INT, page_end INT, is_lexicon INT, general INT,
  types TEXT, perils TEXT, topics TEXT
);
CREATE INDEX IF NOT EXISTS ix_clauses_contract ON clauses(contract_id, ord);
CREATE TABLE IF NOT EXISTS clause_tags (
  clause_id TEXT REFERENCES clauses(id) ON DELETE CASCADE, contract_id TEXT, kind TEXT, value TEXT
);
CREATE INDEX IF NOT EXISTS ix_tags ON clause_tags(kind, value, contract_id);
CREATE VIRTUAL TABLE IF NOT EXISTS clauses_fts USING fts5(
  clause_id UNINDEXED, contract_id UNINDEXED, body, tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS queries (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, contract_id TEXT, question TEXT,
  verdict TEXT, n_citations INT, n_unverified INT, latency_ms INT, model TEXT
);
"""


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "contrat"


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---------- ingestion ----------
    def ingest_pdf(self, pdf_path: str | Path, name: str | None = None, llm=None) -> dict:
        clauses, pages, title = parse_pdf(pdf_path)
        if not clauses:
            raise ValueError("Aucune clause détectée : le PDF est peut-être scanné (pas de texte) ou mal structuré.")
        cid = slugify(name or Path(pdf_path).stem)
        with self.conn() as c:
            c.execute("DELETE FROM clauses_fts WHERE contract_id = ?", (cid,))
            c.execute("DELETE FROM clause_tags WHERE contract_id = ?", (cid,))
            c.execute("DELETE FROM clauses WHERE contract_id = ?", (cid,))
            c.execute("DELETE FROM contracts WHERE id = ?", (cid,))
            c.execute("INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?)",
                      (cid, name or Path(pdf_path).stem, title, Path(pdf_path).name, pages, len(clauses),
                       "llm" if llm else "rules", time.time()))
            for cl in clauses:
                tags = tag_rules(cl.ref, cl.article, cl.chapter, cl.text, cl.is_lexicon)
                if llm is not None and not cl.is_lexicon:
                    tags = tag_with_llm(llm, cl.ref, cl.article, cl.chapter, cl.text, tags)
                clause_id = f"{cid}:{cl.order:04d}"
                c.execute("INSERT INTO clauses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (clause_id, cid, cl.order, cl.ref, cl.chapter, cl.article, cl.text,
                           cl.page_start, cl.page_end, int(cl.is_lexicon), int(tags["general"]),
                           dumps(tags["types"]), dumps(tags["perils"]), dumps(tags["topics"])))
                rows = [(clause_id, cid, "type", t) for t in tags["types"]]
                rows += [(clause_id, cid, "peril", p) for p in tags["perils"]]
                rows += [(clause_id, cid, "heading_peril", p) for p in tags["heading_perils"]]
                rows += [(clause_id, cid, "topic", t) for t in tags["topics"]]
                c.executemany("INSERT INTO clause_tags VALUES (?,?,?,?)", rows)
                body = f"{cl.article} {cl.ref} {cl.text}"
                c.execute("INSERT INTO clauses_fts VALUES (?,?,?)", (clause_id, cid, body))
        return self.get_contract(cid)

    # ---------- reads ----------
    @staticmethod
    def _clause(row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in ("types", "perils", "topics"):
            d[k] = json.loads(d[k])
        d["is_lexicon"] = bool(d["is_lexicon"])
        d["general"] = bool(d["general"])
        return d

    def list_contracts(self) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM contracts ORDER BY ingested_at")]

    def get_contract(self, cid: str) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM contracts WHERE id = ?", (cid,)).fetchone()
            return dict(r) if r else None

    def clauses(self, cid: str) -> list[dict]:
        with self.conn() as c:
            return [self._clause(r) for r in
                    c.execute("SELECT * FROM clauses WHERE contract_id = ? ORDER BY ord", (cid,))]

    def clauses_by_ids(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        with self.conn() as c:
            q = f"SELECT * FROM clauses WHERE id IN ({','.join('?' * len(ids))}) ORDER BY contract_id, ord"
            return [self._clause(r) for r in c.execute(q, ids)]

    def ids_with_tags(self, cid: str | None, kind: str, values: list[str]) -> list[str]:
        if not values:
            return []
        q = f"SELECT DISTINCT clause_id FROM clause_tags WHERE kind = ? AND value IN ({','.join('?' * len(values))})"
        args: list = [kind, *values]
        if cid:
            q += " AND contract_id = ?"
            args.append(cid)
        with self.conn() as c:
            return [r[0] for r in c.execute(q, args)]

    def general_ids(self, cid: str) -> list[str]:
        with self.conn() as c:
            return [r[0] for r in c.execute(
                "SELECT id FROM clauses WHERE contract_id = ? AND general = 1", (cid,))]

    def lexicon(self, cid: str) -> list[dict]:
        with self.conn() as c:
            return [self._clause(r) for r in c.execute(
                "SELECT * FROM clauses WHERE contract_id = ? AND is_lexicon = 1 ORDER BY ord", (cid,))]

    def fts(self, cid: str, terms: list[str], k: int = 8) -> list[tuple[str, float]]:
        toks = []
        for t in terms:
            for w in re.findall(r"[\wÀ-ÿ]+", t.lower()):
                if len(w) < 3 or w in STOP:
                    continue
                toks.append(f'"{stem(w)}"*' if len(w) >= 5 else f'"{w}"')
        if not toks:
            return []
        q = " OR ".join(dict.fromkeys(toks))
        with self.conn() as c:
            rows = c.execute("SELECT clause_id, bm25(clauses_fts) AS s FROM clauses_fts "
                             "WHERE clauses_fts MATCH ? AND contract_id = ? ORDER BY s LIMIT ?", (q, cid, k))
            return [(r[0], r[1]) for r in rows]

    def compare(self, peril: str | None, topic: str | None, ctype: str | None) -> list[dict]:
        """Structured query across all contracts — the 'hundreds of contracts' answer."""
        conds, args = [], []
        for kind, val in (("peril", peril), ("topic", topic), ("type", ctype)):
            if val:
                conds.append("EXISTS (SELECT 1 FROM clause_tags t WHERE t.clause_id = c.id AND t.kind = ? AND t.value = ?)")
                args += [kind, val]
        where = " AND ".join(conds) or "1=1"
        with self.conn() as c:
            rows = c.execute(f"SELECT c.* FROM clauses c WHERE {where} ORDER BY c.contract_id, c.ord", args)
            return [self._clause(r) for r in rows]

    def log_query(self, **kw) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO queries (ts, contract_id, question, verdict, n_citations, n_unverified, latency_ms, model)"
                      " VALUES (?,?,?,?,?,?,?,?)",
                      (time.time(), kw.get("contract_id"), kw.get("question"), kw.get("verdict"),
                       kw.get("n_citations"), kw.get("n_unverified"), kw.get("latency_ms"), kw.get("model")))


STOP = set("""les des une est pas que qui dans pour sur par avec son ses aux mon mes elle ils elles
nous vous etait était sont été être avoir suis mais donc alors cette ces leur leurs tout tous
quand pendant comme plus moins très bien aussi quoi est-ce couvert couverte assurance suis-je""".split())


def stem(w: str) -> str:
    """Very light French stemming for prefix search (volé -> vol, vélos -> vélo)."""
    for suf in ("ements", "ement", "ations", "ation", "ées", "és", "ée", "er", "es", "s", "é", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w
