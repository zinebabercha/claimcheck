"""Question -> verdict, in four auditable steps.

1. Analyse   : the LLM turns the claim into structured facts (perils, goods/places, search terms).
2. Retrieve  : SQL on clause tags (structured) + full-text search (lexical) + lexicon definitions
               + general exclusions. Every retrieved clause carries the reason it was retrieved.
3. Decide    : the LLM answers ONLY from the retrieved clauses, with clause ids and exact quotes,
               and must say "incertain" when facts are missing or the text is ambiguous.
4. Verify    : every quote is checked against the clause text in the database. Quotes that
               cannot be found are discarded; a firm verdict with no verified support is
               downgraded to "incertain". The model cannot cite a clause that does not exist.
"""
from __future__ import annotations

import difflib
import re
import time
import unicodedata

from .llm import LLMError
from .store import STOP, Store, stem
from .tagging import PERILS, TOPICS, _match, fold

VERDICTS = ("couvert", "non_couvert", "incertain")
MAX_CLAUSES = 28
MAX_DEFINITIONS = 6
GENERIC_TERMS = {"vous", "nous", "indemnite", "sinistre", "conditions particulieres", "preneur d'assurance"}

ANALYSE_SYSTEM = f"""Tu es gestionnaire sinistres en assurance habitation. Tu analyses la description d'un sinistre
AVANT de lire le contrat. Réponds en JSON :
{{
  "language": "fr" | "en" | "de" | ...  (langue de la question),
  "perils": [...],          // parmi: {", ".join(PERILS)}
  "topics": [...],          // parmi: {", ".join(TOPICS)}
  "facts": [...],           // faits établis par la question, phrases courtes
  "unknowns": [...],        // faits décisifs que la question ne précise pas (effraction ? flammes ? option souscrite ?)
  "search_terms": [...]     // 4 à 10 mots du vocabulaire des contrats d'assurance (ex: effraction, parties communes, embrasement)
}}
N'utilise que les valeurs des listes pour perils et topics. Ne décide pas encore si c'est couvert."""

DECIDE_SYSTEM = """Tu es un analyste sinistres rigoureux. Tu détermines si un sinistre est couvert en t'appuyant
UNIQUEMENT sur les clauses fournies, identifiées par [C1], [C2]...

Règles :
- N'utilise aucune connaissance extérieure au contrat. Si les clauses fournies ne suffisent pas, dis-le.
- Chaque étape du raisonnement cite les identifiants de clauses qui la justifient.
- Chaque citation reprend un extrait EXACT (copié mot pour mot, 5 à 40 mots) de la clause citée.
- Vérifie dans l'ordre : le bien est-il assuré ? le péril est-il garanti ? les conditions de garantie sont-elles
  remplies ? une exclusion (spécifique ou générale) s'applique-t-elle ? une définition du lexique change-t-elle le sens ?
- "couvert" ou "non_couvert" quand les clauses et les faits donnés suffisent à conclure.
- Les garanties de base des conditions générales sont réputées souscrites. Une garantie que le contrat présente
  comme optionnelle (accordée seulement si elle figure aux conditions particulières) ne l'est pas, sauf si
  l'assuré dit l'avoir souscrite : la réponse dépend alors de cette option.
- Franchise, plafond, montant, vétusté ou délai de déclaration changent le MONTANT, pas le principe de la
  couverture : ils ne justifient pas « incertain ». Mentionne-les dans le résumé ou les limites.
- Présume la bonne foi et les faits ordinaires d'un récit : n'invente pas un défaut d'entretien, une faute
  intentionnelle ou une circonstance que rien dans le récit ne suggère. Tu peux les citer dans missing_facts.
- "incertain" uniquement si un fait manquant et plausible au vu du récit, une option non précisée ou une
  clause réellement ambiguë peut faire basculer le verdict. Dans ce cas, donne les scénarios ("si ... alors ...").
- Mieux vaut un "incertain" bien justifié qu'une réponse affirmative sans appui ; mais un « incertain » par
  simple prudence, quand le contrat répond clairement, est aussi une erreur.
- Réponds dans la langue indiquée.

Format JSON :
{
  "verdict": "couvert" | "non_couvert" | "incertain",
  "confidence": "haute" | "moyenne" | "faible",
  "summary": "2 à 3 phrases claires pour l'assuré",
  "reasoning": [{"step": "...", "clause_ids": ["C3"]}],
  "citations": [{"clause_id": "C3", "quote": "extrait exact", "role": "garantie|exclusion|condition|definition|obligation"}],
  "missing_facts": ["question à poser à l'assuré", ...],
  "scenarios": [{"if": "...", "then": "couvert|non_couvert|incertain", "clause_ids": ["C3"]}],
  "limits": "ce que le système ne peut pas savoir (ex: conditions particulières non fournies)"
}"""


# ---------------------------------------------------------------- text utils
def norm(s: str) -> str:
    """Lowercase, unify quotes/spaces and drop accents (models often 'fix' or drop them in quotes)."""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'").replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"')
    s = s.replace(" ", " ").replace(" ", " ")
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip().lower()


def _widen(text: str, s: int, e: int) -> tuple[int, int]:
    """Quotes can start or stop mid-word (truncated by the model): widen to whole words for display."""
    while s > 0 and text[s - 1].isalnum():
        s -= 1
    while e < len(text) and text[e].isalnum():
        e += 1
    while s < e and text[s].isspace():
        s += 1
    return s, e


def locate_quote(quote: str, text: str, min_ratio: float = 0.85) -> tuple[int, int, float] | None:
    """Find `quote` in `text`; return (start, end, score) in ORIGINAL text coordinates, or None.

    Exact match after normalisation first, then a fuzzy sliding window (models sometimes
    change an apostrophe or drop a word); below `min_ratio` the quote is rejected.
    """
    q = norm(quote).strip(" .\"'…")
    if len(q) < 8:
        return None
    # map normalised positions back to original text
    norm_chars, index = [], []
    prev_space = False
    for i, ch in enumerate(text):
        n = norm(ch) if ch.strip() else " "
        if n == " ":
            if prev_space or not norm_chars:
                continue
            prev_space = True
        else:
            prev_space = False
        for nc in n:
            norm_chars.append(nc)
            index.append(i)
    t = "".join(norm_chars)
    pos = t.find(q)
    if pos >= 0:
        return _widen(text, index[pos], index[pos + len(q) - 1] + 1) + (1.0,)
    # fuzzy: slide a window of the quote's length over the clause (clauses are short, this is cheap)
    best = (0.0, 0, 0)
    L = len(q)
    for size in (L, int(L * 1.1), int(L * 0.9)):
        for s in range(0, max(1, len(t) - size + 1)):
            win = t[s: s + size]
            sm = difflib.SequenceMatcher(None, win, q, autojunk=False)
            if sm.real_quick_ratio() < best[0] or sm.quick_ratio() < max(best[0], min_ratio):
                continue
            r = sm.ratio()
            if r > best[0]:
                best = (r, s, s + len(win))
    if best[0] >= min_ratio and best[2] > best[1]:
        s, e = index[best[1]], index[min(best[2], len(index)) - 1] + 1
        return _widen(text, s, e) + (round(best[0], 3),)
    return None


# ---------------------------------------------------------------- pipeline
class Reasoner:
    def __init__(self, store: Store, llm):
        self.store = store
        self.llm = llm

    # -- step 1
    @staticmethod
    def analyse_rules(question: str) -> dict:
        """Keyword fallback (no LLM): used if the analysis call fails, and for offline retrieval evaluation."""
        q = fold(question)
        words = [w for w in re.findall(r"[\wà-ÿ]+", q) if len(w) > 3 and w not in STOP]
        return {"language": "fr", "perils": _match(PERILS, q), "topics": _match(TOPICS, q),
                "facts": [], "unknowns": [], "search_terms": words[:12], "fallback": True}

    def analyse(self, question: str) -> dict:
        try:
            out = self.llm.json(ANALYSE_SYSTEM, f"Sinistre : {question}")
        except LLMError:
            raise
        except Exception:
            return self.analyse_rules(question)
        return {
            "language": str(out.get("language", "fr"))[:5],
            "perils": [p for p in out.get("perils", []) if p in PERILS],
            "topics": [t for t in out.get("topics", []) if t in TOPICS],
            "facts": [str(x) for x in out.get("facts", [])][:10],
            "unknowns": [str(x) for x in out.get("unknowns", [])][:10],
            "search_terms": [str(x) for x in out.get("search_terms", [])][:12],
        }

    # -- step 2
    def retrieve(self, contract_id: str, question: str, analysis: dict) -> list[dict]:
        reasons: dict[str, list[str]] = {}
        score: dict[str, float] = {}

        def add(ids, why, w):
            for i in ids:
                reasons.setdefault(i, [])
                if why not in reasons[i]:
                    reasons[i].append(why)
                score[i] = score.get(i, 0) + w

        perils, topics = analysis["perils"], analysis["topics"]
        # structured: clauses of the article dedicated to the peril (strongest signal)
        for p in perils:
            add(self.store.ids_with_tags(contract_id, "heading_peril", [p]), f"article « {p} »", 3.0)
            add(self.store.ids_with_tags(contract_id, "peril", [p]), f"mentionne le péril « {p} »", 1.0)
        for t in topics:
            add(self.store.ids_with_tags(contract_id, "topic", [t]), f"concerne « {t} »", 1.5)
        # general exclusions / conditions apply to every claim
        add(self.store.general_ids(contract_id), "disposition générale", 0.8)
        # lexical
        for rank, (cid, _) in enumerate(self.store.fts(contract_id, [question, *analysis["search_terms"]], k=10)):
            add([cid], "recherche plein texte", 2.0 - rank * 0.15)

        clauses = {c["id"]: c for c in self.store.clauses_by_ids(list(reasons))}
        # lexicon: definitions of terms used in the question first, then in the clauses most specific to the claim.
        # Capped: long contracts mention dozens of defined terms, and generic ones ("vous", "nous") add noise.
        def stems_of(text):
            return {stem(w) for w in re.findall(r"[\wà-ÿ]+", norm(text))}

        q_stems = stems_of(question + " " + " ".join(analysis["search_terms"]))
        top = sorted((c for c in clauses.values() if not c["is_lexicon"]), key=lambda c: -score.get(c["id"], 0))[:8]
        top_stems = stems_of(" ".join(c["text"] for c in top))
        lex_hits = []
        for d in self.store.lexicon(contract_id):
            term = norm(d["ref"].split(":", 1)[-1])
            words = [stem(w) for w in re.findall(r"[\wà-ÿ]+", term) if len(w) > 2]
            if not words or term in GENERIC_TERMS:
                continue
            if all(w in q_stems for w in words):
                lex_hits.append((2.0, d))
            elif all(w in top_stems for w in words):
                lex_hits.append((1.0, d))
        for w, d in sorted(lex_hits, key=lambda x: -x[0])[:MAX_DEFINITIONS]:
            add([d["id"]], "définition du lexique", 1.2 * w)
            clauses[d["id"]] = d

        ranked = sorted(clauses.values(), key=lambda c: -score.get(c["id"], 0))[:MAX_CLAUSES]
        ranked.sort(key=lambda c: c["ord"])  # present in document order: easier to reason on
        for c in ranked:
            c["retrieval_reasons"] = reasons.get(c["id"], [])
            c["retrieval_score"] = round(score.get(c["id"], 0), 2)
        return ranked

    # -- step 3
    def decide(self, question: str, analysis: dict, clauses: list[dict]) -> tuple[dict, dict[str, dict]]:
        labels = {f"C{i + 1}": c for i, c in enumerate(clauses)}
        ctx = "\n\n".join(f"[{lab}] {c['ref']} — {c['article'] or c['chapter']} (p.{c['page_start']})\n{c['text']}"
                          for lab, c in labels.items())
        user = (f"Langue de réponse : {analysis['language']}\n\nSinistre : {question}\n\n"
                f"Faits établis : {analysis['facts']}\nPoints à vérifier : {analysis['unknowns']}\n\n"
                f"Clauses du contrat :\n{ctx}")
        return self.llm.json(DECIDE_SYSTEM, user), labels

    # -- step 4
    @staticmethod
    def verify(raw: dict, labels: dict[str, dict]) -> dict:
        warnings: list[str] = []
        verdict = raw.get("verdict") if raw.get("verdict") in VERDICTS else "incertain"
        citations, unverified = [], []
        for cit in raw.get("citations", []) or []:
            lab = str(cit.get("clause_id", "")).strip("[] ")
            c = labels.get(lab)
            quote = str(cit.get("quote", ""))
            loc = locate_quote(quote, c["text"]) if c else None
            if not c or not loc:
                unverified.append({"clause_id": lab, "quote": quote,
                                   "why": "clause inconnue" if not c else "extrait introuvable dans la clause"})
                continue
            s, e, sc = loc
            citations.append({"clause_id": c["id"], "label": lab, "ref": c["ref"], "page": c["page_start"],
                              "quote": c["text"][s:e], "start": s, "end": e, "match": sc,
                              "role": cit.get("role", "")})

        def map_ids(ids):
            return [labels[i]["id"] for i in (str(x).strip("[] ") for x in ids or []) if i in labels]

        def clean(text) -> str:
            """Replace internal labels ([C8], C8) by the contract reference the reader knows (7.3)."""
            def sub(m):
                c = labels.get(m.group(1))
                return c["ref"].replace("Lexique : ", "définition « ") + (" »" if c["is_lexicon"] else "") if c else m.group(0)
            out = re.sub(r"\[?\b(C\d{1,3})\b\]?", sub, str(text or ""))
            out = re.sub(r"\s*(selon|cf\.?|voir)\s*\(?\s*\)?\s*([.,;])", r"\2", out)
            return out.strip()

        reasoning = [{"step": clean(r.get("step")), "clause_ids": map_ids(r.get("clause_ids"))}
                     for r in raw.get("reasoning", []) or []]
        scenarios = [{"if": clean(s.get("if")),
                      "then": s.get("then") if s.get("then") in VERDICTS else "incertain",
                      "clause_ids": map_ids(s.get("clause_ids"))} for s in raw.get("scenarios", []) or []]
        if unverified:
            warnings.append(f"{len(unverified)} citation(s) écartée(s) : texte introuvable dans le contrat.")
        if verdict != "incertain" and not citations:
            warnings.append("Verdict ramené à « incertain » : aucune citation vérifiable ne le justifie.")
            verdict = "incertain"
        confidence = raw.get("confidence") if raw.get("confidence") in ("haute", "moyenne", "faible") else "faible"
        if verdict == "incertain" and confidence == "haute":
            confidence = "moyenne"
        # a firm verdict that flips in some scenario cannot be "haute" confidence
        if verdict != "incertain" and confidence == "haute" and any(sc["then"] != verdict for sc in scenarios):
            confidence = "moyenne"
        return {
            "verdict": verdict, "confidence": confidence,
            "summary": clean(raw.get("summary")),
            "reasoning": reasoning, "citations": citations, "unverified_citations": unverified,
            "missing_facts": [clean(x) for x in raw.get("missing_facts", []) or []],
            "scenarios": scenarios, "limits": clean(raw.get("limits")), "warnings": warnings,
        }

    def ask(self, contract_id: str, question: str) -> dict:
        t0 = time.time()
        analysis = self.analyse(question)
        t1 = time.time()
        clauses = self.retrieve(contract_id, question, analysis)
        t2 = time.time()
        raw, labels = self.decide(question, analysis, clauses)
        t3 = time.time()
        result = self.verify(raw, labels)
        result["trace"] = {
            "analysis": analysis,
            "retrieved": [{"clause_id": c["id"], "label": lab, "ref": c["ref"], "reasons": c["retrieval_reasons"],
                           "score": c["retrieval_score"]} for lab, c in labels.items()],
            "timings_ms": {"analyse": int((t1 - t0) * 1000), "retrieve": int((t2 - t1) * 1000),
                           "decide": int((t3 - t2) * 1000)},
            "model": getattr(self.llm, "model", "?"),
            "usage": dict(getattr(self.llm, "usage", {})),
        }
        self.store.log_query(contract_id=contract_id, question=question, verdict=result["verdict"],
                             n_citations=len(result["citations"]), n_unverified=len(result["unverified_citations"]),
                             latency_ms=int((time.time() - t0) * 1000), model=result["trace"]["model"])
        return result
