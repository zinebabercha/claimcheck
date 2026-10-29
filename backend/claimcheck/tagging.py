"""Structured tagging of clauses.

Each clause gets:
- types  : what the clause does (garantie, exclusion, condition, obligation, definition, champ)
- perils : which insured event it concerns (vol, incendie, degats_eaux, ...)
- topics : which goods / places it concerns (parties_communes, exterieur, velo, ...)

These tags are stored as rows (clause_tags) so they can be queried with SQL
across hundreds of contracts. A rule-based tagger runs by default (free,
deterministic, auditable); `tag_with_llm` refines the tags with Mistral.
"""
from __future__ import annotations

import json
import re
import unicodedata

PERILS: dict[str, list[str]] = {
    "incendie": [r"incendi", r"explosion", r"implosion", r"foudre", r"fum[ée]e", r"suie", r"br[ûu]lure",
                 r"embrasement", r"flamme", r"roussissement", r"bougie"],
    "degats_eaux": [r"d[ée]g[âa]ts? des eaux", r"[ée]coulement", r"infiltration", r"conduite", r"fuite",
                    r"humidit[ée]", r"condensation", r"sanitaire"],
    "tempete": [r"temp[êe]te", r"gr[êe]le", r"neige", r"\bvent\b"],
    "vol": [r"\bvols?\b", r"cambriol", r"effraction", r"escalade", r"fausses cl[ée]s", r"vandalisme", r"antivol"],
    "bris_vitrage": [r"vitrage", r"\bvitres?\b", r"miroir", r"\bbris\b", r"vitroc[ée]ramique"],
    "rc": [r"responsabilit[ée] civile", r"\btiers\b"],
    "catnat": [r"inondation", r"catastrophe naturelle", r"tremblement de terre", r"glissement de terrain"],
}

TOPICS: dict[str, list[str]] = {
    "parties_communes": [r"parties communes", r"local v[ée]los?", r"cave collective", r"copropri[ée]t[ée]"],
    "dependances": [r"d[ée]pendance", r"\bgarage", r"\bcave\b", r"grenier"],
    "exterieur": [r"ext[ée]rieur", r"jardin", r"terrasse", r"balcon", r"barbecue"],
    "velo": [r"v[ée]los?\b", r"bicyclette", r"trottinette"],
    "objets_valeur": [r"objets? de valeur", r"bijou", r"montre", r"[œo]euvres? d.art"],
    "electronique": [r"[ée]lectroni", r"ordinateur", r"t[ée]l[ée]phone"],
    "batiment": [r"b[âa]timent", r"toiture", r"\bmurs?\b"],
    "vehicule": [r"v[ée]hicule", r"voiture"],
    "inoccupation": [r"inoccup", r"absence", r"vacances", r"non verrouill"],
    "franchise_plafond": [r"franchise", r"limit[ée]e? [àa]", r"plafon", r"v[ée]tust[ée]", r"maximum de"],
}

TYPE_PATTERNS: list[tuple[str, str]] = [
    ("exclusion", r"ne sont (jamais |pas )?(couverts|garantis|assur[ée]s|consid[ée]r[ée]s)|sont exclus|"
                  r"nous ne (couvrons|garantissons|prenons)|[àa] l.exclusion|\bexclusions?\b|ne sont pas couverts"),
    ("condition", r"uniquement si|[àa] condition que|n.est acquise que si|que si\b|pour autant que|"
                  r"limit[ée]e? [àa]|franchise|plafon|r[ée]duire|r[ée]duite"),
    ("obligation", r"\bdoit\b|\bdoivent\b|obligation|d[ée]lai|dans les \d+ (heures|jours)|d[ée]clarer"),
    ("garantie", r"nous couvrons|sont couverts|est couvert|sont garantis|nous garantissons|garantie s.exerce|"
                 r"sont toutefois couverts|couverts uniquement"),
    ("champ", r"sont assur[ée]s|biens assur[ée]s|lieu de la garantie|s.exercent"),
]

ALL_TYPES = ["garantie", "exclusion", "condition", "obligation", "definition", "champ", "autre"]


def fold(s: str) -> str:
    """Lowercase + keep accents (patterns handle both); normalise apostrophes/quotes."""
    s = s.replace("’", "'").replace("‘", "'").replace("«", '"').replace("»", '"')
    return unicodedata.normalize("NFC", s).lower()


def _match(groups: dict[str, list[str]], text: str) -> list[str]:
    return [k for k, pats in groups.items() if any(re.search(p, text) for p in pats)]


def tag_rules(ref: str, article: str, chapter: str, text: str, is_lexicon: bool) -> dict:
    body = fold(text)
    heading = fold(article + " " + chapter)
    if is_lexicon:
        types = ["definition"]
    else:
        types = [t for t, p in TYPE_PATTERNS if re.search(p, body)] or ["autre"]
    # peril of the article heading is authoritative; body keywords add secondary perils
    heading_perils = _match(PERILS, fold(article))
    body_perils = _match(PERILS, body)
    perils = sorted(set(heading_perils) | set(body_perils))
    general = bool(re.search(r"exclusions? (g[ée]n[ée]rales|applicables [àa] toutes)|toutes les garanties|en cas de sinistre",
                             heading)) or bool(re.search(
        r"tant pour les garanties de base que pour les garanties optionnelles|applicables? [àa] toutes les garanties|"
        r"toujours exclus|obligations de l.assur[ée] en cas de sinistre", body))
    topics = sorted(_match(TOPICS, body))
    return {"types": types, "perils": perils, "topics": topics, "general": general,
            "heading_perils": heading_perils}


LLM_TAG_SYSTEM = """Tu classes des clauses de conditions générales d'assurance habitation.
Réponds en JSON: {"types": [...], "perils": [...], "topics": [...], "general": bool}
- types parmi: garantie, exclusion, condition, obligation, definition, champ, autre (plusieurs possibles)
- perils parmi: %s (liste vide si la clause n'est liée à aucun péril précis)
- topics parmi: %s
- general = true si la clause s'applique à toutes les garanties (exclusion générale, franchise, obligations en cas de sinistre)
N'invente aucune valeur hors de ces listes.""" % (", ".join(PERILS), ", ".join(TOPICS))


def tag_with_llm(llm, ref: str, article: str, chapter: str, text: str, fallback: dict) -> dict:
    try:
        out = llm.json(LLM_TAG_SYSTEM, f"Chapitre: {chapter}\nArticle: {article}\nClause {ref}: {text}")
        res = {
            "types": [t for t in out.get("types", []) if t in ALL_TYPES] or fallback["types"],
            "perils": [p for p in out.get("perils", []) if p in PERILS],
            "topics": [t for t in out.get("topics", []) if t in TOPICS],
            "general": bool(out.get("general", fallback["general"])),
            "heading_perils": fallback["heading_perils"],
        }
        return res
    except Exception:  # never lose a clause because the LLM failed
        return fallback


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False)
