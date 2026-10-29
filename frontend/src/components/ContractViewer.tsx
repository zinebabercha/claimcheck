import { useEffect, useMemo, useRef, useState } from "react";
import type { Citation, Clause } from "../types";
import { TYPE_LABEL, label } from "../labels";

interface Props {
  clauses: Clause[];
  citations: Citation[];
  retrievedIds: Set<string>;
  focusId: string | null;
  focusTick: number;
  pdfUrl: string | null;
}

function highlight(text: string, cits: Citation[]) {
  if (!cits.length) return text;
  const spans = [...cits].sort((a, b) => a.start - b.start);
  const out: (string | React.ReactElement)[] = [];
  let pos = 0;
  spans.forEach((c, i) => {
    if (c.start < pos) return; // overlapping quote: keep the first
    out.push(text.slice(pos, c.start));
    out.push(
      <mark key={i} className={`hl role-${c.role || "x"}`} title={`Cité par l'analyse (${c.label})`}>
        {text.slice(c.start, c.end)}
      </mark>,
    );
    pos = c.end;
  });
  out.push(text.slice(pos));
  return out;
}

export function ContractViewer({ clauses, citations, retrievedIds, focusId, focusTick, pdfUrl }: Props) {
  const [filter, setFilter] = useState("");
  const [onlyRetrieved, setOnlyRetrieved] = useState(false);
  const refs = useRef<Record<string, HTMLElement | null>>({});
  const citedBy = useMemo(() => {
    const m: Record<string, Citation[]> = {};
    citations.forEach((c) => (m[c.clause_id] ??= []).push(c));
    return m;
  }, [citations]);

  useEffect(() => {
    if (onlyRetrieved && retrievedIds.size === 0) setOnlyRetrieved(false);
  }, [retrievedIds, onlyRetrieved]);

  useEffect(() => {
    if (!focusId) return;
    const el = refs.current[focusId];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.remove("flash");
      void el.offsetWidth;
      el.classList.add("flash");
    }
  }, [focusId, focusTick]);

  const f = filter.trim().toLowerCase();
  const visible = clauses.filter(
    (c) =>
      (!onlyRetrieved || retrievedIds.has(c.id)) &&
      (!f || c.text.toLowerCase().includes(f) || c.ref.toLowerCase().includes(f)),
  );

  let lastHeading = "";
  return (
    <section className="viewer" aria-label="Contrat">
      <div className="viewer-bar">
        <input
          className="search"
          placeholder="Rechercher dans le contrat…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <label className={`toggle ${retrievedIds.size === 0 ? "disabled" : ""}`}>
          <input
            type="checkbox"
            checked={onlyRetrieved}
            disabled={retrievedIds.size === 0}
            onChange={(e) => setOnlyRetrieved(e.target.checked)}
          />
          Clauses lues par l'analyse ({retrievedIds.size})
        </label>
        {pdfUrl && (
          <a className="pdf-link" href={pdfUrl} target="_blank" rel="noreferrer">
            PDF ↗
          </a>
        )}
      </div>
      <div className="doc">
        {visible.length === 0 && <p className="muted pad">Aucune clause ne correspond.</p>}
        {visible.map((c) => {
          const heading = c.is_lexicon ? c.chapter : c.article || c.chapter;
          const showHeading = heading !== lastHeading;
          lastHeading = heading;
          const cited = citedBy[c.id] ?? [];
          const cls = ["clause", cited.length ? "cited" : "", retrievedIds.has(c.id) ? "retrieved" : ""].join(" ");
          return (
            <div key={c.id}>
              {showHeading && <h3 className="doc-heading">{heading}</h3>}
              <article className={cls} ref={(el) => void (refs.current[c.id] = el)} id={`clause-${c.id}`}>
                <div className="clause-meta">
                  <span className="ref">{c.ref.replace(/^Lexique : /, "")}</span>
                  <span className="page">p.{c.page_start}</span>
                  {c.types
                    .filter((t) => t !== "autre")
                    .map((t) => (
                      <span key={t} className={`tag t-${t}`}>
                        {label(TYPE_LABEL, t)}
                      </span>
                    ))}
                  {cited.length > 0 && <span className="cited-badge">cité</span>}
                </div>
                <p className="clause-text">{highlight(c.text, cited)}</p>
              </article>
            </div>
          );
        })}
      </div>
    </section>
  );
}
