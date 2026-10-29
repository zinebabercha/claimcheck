import { useEffect, useState } from "react";
import { api } from "../api";
import type { CompareGroup, Meta } from "../types";
import { PERIL_LABEL, TOPIC_LABEL, TYPE_LABEL, label } from "../labels";

export function ComparePanel({ meta, nContracts }: { meta: Meta | null; nContracts: number }) {
  const [peril, setPeril] = useState("vol");
  const [topic, setTopic] = useState("parties_communes");
  const [type, setType] = useState("");
  const [groups, setGroups] = useState<CompareGroup[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .compare({ peril, topic, type })
      .then((g) => {
        setGroups(g);
        setErr("");
      })
      .catch((e) => setErr(String(e.message ?? e)));
  }, [peril, topic, type, nContracts]);

  const sql =
    "SELECT c.* FROM clauses c WHERE " +
    [
      peril && `has_tag(c,'peril','${peril}')`,
      topic && `has_tag(c,'topic','${topic}')`,
      type && `has_tag(c,'type','${type}')`,
    ]
      .filter(Boolean)
      .join(" AND ");

  return (
    <div className="compare">
      <p className="lede">
        Les clauses de chaque contrat sont extraites et étiquetées (type, péril, bien concerné) dans une table SQL. On peut
        donc interroger des centaines de contrats par une requête structurée, sans renvoyer les PDF au modèle.
      </p>
      <div className="filters">
        <label>
          Péril
          <select value={peril} onChange={(e) => setPeril(e.target.value)}>
            <option value="">Tous</option>
            {meta?.perils.map((p) => (
              <option key={p} value={p}>
                {label(PERIL_LABEL, p)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Bien / lieu
          <select value={topic} onChange={(e) => setTopic(e.target.value)}>
            <option value="">Tous</option>
            {meta?.topics.map((p) => (
              <option key={p} value={p}>
                {label(TOPIC_LABEL, p)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Type de clause
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">Tous</option>
            {Object.keys(TYPE_LABEL).map((p) => (
              <option key={p} value={p}>
                {label(TYPE_LABEL, p)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <pre className="sql">{sql}</pre>
      {err && <p className="error">{err}</p>}
      {groups.length === 0 && !err && <p className="muted">Aucune clause ne correspond à ces critères.</p>}
      <div className="compare-grid">
        {groups.map((g) => (
          <div key={g.contract_id} className="compare-col">
            <h3>
              {g.name} <span className="count">{g.clauses.length}</span>
            </h3>
            {g.clauses.map((c) => (
              <article key={c.id} className="clause compact">
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
                </div>
                <p className="clause-text">{c.text}</p>
              </article>
            ))}
          </div>
        ))}
      </div>
      {nContracts < 2 && (
        <p className="muted small">Ajoutez un second contrat (bouton « Ajouter un contrat ») pour les comparer côte à côte.</p>
      )}
    </div>
  );
}
