import { useState } from "react";
import type { AskResult, Clause } from "../types";
import { PERIL_LABEL, TOPIC_LABEL, VERDICT_LABEL, label } from "../labels";

interface Props {
  result: AskResult;
  clauseById: Record<string, Clause>;
  onFocus: (clauseId: string) => void;
}

function ClauseChip({ id, clauseById, onFocus }: { id: string; clauseById: Record<string, Clause>; onFocus: (id: string) => void }) {
  const c = clauseById[id];
  return (
    <button className="chip" onClick={() => onFocus(id)} title={c?.text.slice(0, 220)}>
      {c ? c.ref.replace(/^Lexique : /, "Déf. ") : id}
    </button>
  );
}

export function ResultPanel({ result, clauseById, onFocus }: Props) {
  const [showTrace, setShowTrace] = useState(false);
  const r = result;
  const t = r.trace;
  const totalMs = Object.values(t.timings_ms).reduce((a, b) => a + b, 0);

  return (
    <div className="result">
      <div className={`verdict v-${r.verdict}`}>
        <div className="verdict-main">
          <span className="verdict-label">{VERDICT_LABEL[r.verdict]}</span>
          <span className="confidence">confiance {r.confidence}</span>
        </div>
        <p className="summary">{r.summary}</p>
      </div>

      {r.warnings.length > 0 && (
        <div className="warn" role="note">
          {r.warnings.map((w, i) => (
            <p key={i}>⚠ {w}</p>
          ))}
        </div>
      )}

      {r.reasoning.length > 0 && (
        <section className="block">
          <h4>Raisonnement</h4>
          <ol className="steps">
            {r.reasoning.map((s, i) => (
              <li key={i}>
                <span>{s.step}</span>
                <span className="chips">
                  {s.clause_ids.map((id) => (
                    <ClauseChip key={id} id={id} clauseById={clauseById} onFocus={onFocus} />
                  ))}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {r.scenarios.length > 0 && (
        <section className="block">
          <h4>Selon les cas</h4>
          <ul className="scenarios">
            {r.scenarios.map((s, i) => (
              <li key={i}>
                <span className="if">Si {s.if.replace(/^si\s+/i, "")}</span>
                <span className={`mini v-${s.then}`}>{VERDICT_LABEL[s.then]}</span>
                <span className="chips">
                  {s.clause_ids.map((id) => (
                    <ClauseChip key={id} id={id} clauseById={clauseById} onFocus={onFocus} />
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {r.missing_facts.length > 0 && (
        <section className="block">
          <h4>À demander à l'assuré</h4>
          <ul className="missing">
            {r.missing_facts.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="block">
        <h4>
          Citations vérifiées <span className="count">{r.citations.length}</span>
        </h4>
        {r.citations.length === 0 && <p className="muted">Aucune citation n'a pu être vérifiée dans le contrat.</p>}
        <ul className="citations">
          {r.citations.map((c, i) => (
            <li key={i}>
              <button className="cite" onClick={() => onFocus(c.clause_id)}>
                <span className="cite-head">
                  <b>{c.ref.replace(/^Lexique : /, "Définition · ")}</b> · p.{c.page}
                  {c.role && <span className={`tag t-${c.role}`}>{c.role}</span>}
                  {c.match < 1 && <span className="fuzzy" title="Citation retrouvée avec de légères différences">≈ {Math.round(c.match * 100)}%</span>}
                </span>
                <q>{c.quote}</q>
              </button>
            </li>
          ))}
        </ul>
        {r.unverified_citations.length > 0 && (
          <details className="dropped">
            <summary>{r.unverified_citations.length} citation(s) écartée(s) par la vérification</summary>
            <ul>
              {r.unverified_citations.map((u, i) => (
                <li key={i}>
                  <code>{u.clause_id}</code> — « {u.quote} » <em>({u.why})</em>
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      {r.limits && (
        <section className="block">
          <h4>Limites</h4>
          <p className="muted">{r.limits}</p>
        </section>
      )}

      <button className="trace-toggle" onClick={() => setShowTrace((s) => !s)}>
        {showTrace ? "Masquer" : "Afficher"} la trace technique
      </button>
      {showTrace && (
        <section className="trace">
          <div className="trace-grid">
            <div>
              <h5>1 · Analyse du sinistre</h5>
              <p>
                <b>Périls :</b> {t.analysis.perils.map((p) => label(PERIL_LABEL, p)).join(", ") || "—"}
              </p>
              <p>
                <b>Biens / lieux :</b> {t.analysis.topics.map((p) => label(TOPIC_LABEL, p)).join(", ") || "—"}
              </p>
              <p>
                <b>Faits :</b> {t.analysis.facts.join(" · ") || "—"}
              </p>
              <p>
                <b>Inconnues :</b> {t.analysis.unknowns.join(" · ") || "—"}
              </p>
              <p>
                <b>Termes cherchés :</b> {t.analysis.search_terms.join(", ")}
              </p>
            </div>
            <div>
              <h5>2 · Clauses récupérées ({t.retrieved.length})</h5>
              <table>
                <tbody>
                  {t.retrieved.map((x) => (
                    <tr key={x.clause_id}>
                      <td>
                        <button className="linklike" onClick={() => onFocus(x.clause_id)}>
                          {x.label} · {x.ref.replace(/^Lexique : /, "Déf. ")}
                        </button>
                      </td>
                      <td className="muted small">{x.reasons.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <p className="muted small">
            Modèle {t.model} · {totalMs} ms (analyse {t.timings_ms.analyse}, recherche {t.timings_ms.retrieve}, décision{" "}
            {t.timings_ms.decide}) · tokens {t.usage.prompt_tokens ?? 0}+{t.usage.completion_tokens ?? 0}
          </p>
        </section>
      )}
    </div>
  );
}
