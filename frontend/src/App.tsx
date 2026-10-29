import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { AskResult, Clause, Contract, Health, Meta } from "./types";
import { ContractViewer } from "./components/ContractViewer";
import { ResultPanel } from "./components/ResultPanel";
import { ComparePanel } from "./components/ComparePanel";

const STEPS = ["Analyse du sinistre", "Recherche des clauses", "Lecture du contrat", "Vérification des citations"];

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [contractId, setContractId] = useState("");
  const [clauses, setClauses] = useState<Clause[]>([]);
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AskResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"ask" | "compare">("ask");
  const [focus, setFocus] = useState<{ id: string | null; tick: number }>({ id: null, tick: 0 });
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadContracts = (select?: string) =>
    api.contracts().then((cs) => {
      setContracts(cs);
      if (select) setContractId(select);
      else if (!contractId && cs.length) setContractId(cs[0].id);
    });

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.meta().then(setMeta).catch(() => undefined);
    loadContracts().catch((e) => setError(String(e.message ?? e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!contractId) return;
    setResult(null);
    api.clauses(contractId).then(setClauses).catch((e) => setError(String(e.message ?? e)));
  }, [contractId]);

  useEffect(() => {
    if (!loading) return;
    setStep(0);
    const t = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 2200);
    return () => clearInterval(t);
  }, [loading]);

  const clauseById = useMemo(() => Object.fromEntries(clauses.map((c) => [c.id, c])), [clauses]);
  const retrievedIds = useMemo(() => new Set(result?.trace.retrieved.map((r) => r.clause_id) ?? []), [result]);
  const contract = contracts.find((c) => c.id === contractId);

  async function submit(q = question) {
    if (q.trim().length < 10 || !contractId) return;
    setQuestion(q);
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const r = await api.ask(contractId, q);
      setResult(r);
      if (r.citations[0]) setFocus({ id: r.citations[0].clause_id, tick: Date.now() });
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }

  async function onUpload(f: File | undefined) {
    if (!f) return;
    const name = window.prompt("Nom du contrat (ex. « Assureur X – Habitation »)", f.name.replace(/\.pdf$/i, ""));
    if (!name) return;
    setUploading(true);
    setError("");
    try {
      const c = await api.upload(f, name, Boolean(health?.llm_configured));
      await loadContracts(c.id);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="logo" aria-hidden>
            §
          </span>
          <div>
            <h1>ClaimCheck</h1>
            <p>Ce sinistre est-il couvert ? Réponse sourcée, clause par clause.</p>
          </div>
        </div>
        <nav className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "ask"} className={tab === "ask" ? "on" : ""} onClick={() => setTab("ask")}>
            Analyser un sinistre
          </button>
          <button
            role="tab"
            aria-selected={tab === "compare"}
            className={tab === "compare" ? "on" : ""}
            onClick={() => setTab("compare")}
          >
            Comparer les contrats
          </button>
        </nav>
        <div className="contract-picker">
          <select value={contractId} onChange={(e) => setContractId(e.target.value)} aria-label="Contrat">
            {contracts.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.n_clauses} clauses
              </option>
            ))}
          </select>
          {health?.upload && (
            <>
              <button className="ghost" disabled={uploading} onClick={() => fileRef.current?.click()}>
                {uploading ? "Ingestion…" : "+ Ajouter un contrat"}
              </button>
              <input ref={fileRef} type="file" accept="application/pdf" hidden onChange={(e) => onUpload(e.target.files?.[0])} />
            </>
          )}
        </div>
      </header>

      {health && !health.llm_configured && (
        <div className="banner">
          Clé Mistral non configurée : le contrat est consultable, mais l'analyse nécessite <code>MISTRAL_API_KEY</code>.
        </div>
      )}
      {error && (
        <div className="banner error" role="alert">
          {error}
          <button className="linklike" onClick={() => setError("")}>
            fermer
          </button>
        </div>
      )}

      {tab === "compare" ? (
        <main className="single">
          <ComparePanel meta={meta} nContracts={contracts.length} />
        </main>
      ) : (
        <main className="split">
          <section className="left">
            <form
              className="ask"
              onSubmit={(e) => {
                e.preventDefault();
                submit();
              }}
            >
              <label htmlFor="q" className="ask-label">
                Décrivez le sinistre
              </label>
              <textarea
                id="q"
                rows={4}
                value={question}
                placeholder="Ex. : On m'a volé mon vélo dans la cave commune de l'immeuble…"
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
                }}
              />
              <div className="ask-row">
                <div className="examples">
                  {meta?.examples.map((ex, i) => (
                    <button type="button" key={i} className="example" onClick={() => submit(ex)} disabled={loading}>
                      {ex.length > 64 ? ex.slice(0, 62) + "…" : ex}
                    </button>
                  ))}
                </div>
                <button className="primary" type="submit" disabled={loading || question.trim().length < 10}>
                  {loading ? "Analyse…" : "Analyser"}
                </button>
              </div>
            </form>

            {loading && (
              <ol className="progress" aria-live="polite">
                {STEPS.map((s, i) => (
                  <li key={s} className={i < step ? "done" : i === step ? "now" : ""}>
                    {s}
                  </li>
                ))}
              </ol>
            )}

            {result && (
              <ResultPanel result={result} clauseById={clauseById} onFocus={(id) => setFocus({ id, tick: Date.now() })} />
            )}

            {!result && !loading && (
              <div className="howto">
                <h4>Comment ça marche</h4>
                <ol>
                  <li>
                    <b>Le contrat est découpé en clauses</b>, pas en morceaux de texte arbitraires : chaque article, sous-article et
                    définition garde sa référence et sa page.
                  </li>
                  <li>
                    <b>Chaque clause est étiquetée</b> (garantie, exclusion, condition, définition ; péril ; bien concerné) dans une
                    table SQL.
                  </li>
                  <li>
                    <b>La question est analysée</b>, puis les clauses pertinentes sont retrouvées par ces étiquettes, par recherche plein
                    texte et via le lexique.
                  </li>
                  <li>
                    <b>Le modèle répond uniquement à partir de ces clauses</b>, avec des citations exactes. Chaque citation est
                    revérifiée dans le texte ; un verdict sans appui vérifiable devient « incertain ».
                  </li>
                </ol>
              </div>
            )}
          </section>

          <section className="right">
            <div className="right-head">
              <h2>{contract?.name ?? "Contrat"}</h2>
              <span className="muted small">
                {contract ? `${contract.pages} pages · ${contract.n_clauses} clauses · étiquetage ${contract.tagger === "llm" ? "LLM" : "règles"}` : ""}
              </span>
            </div>
            <ContractViewer
              clauses={clauses}
              citations={result?.citations ?? []}
              retrievedIds={retrievedIds}
              focusId={focus.id}
              focusTick={focus.tick}
              pdfUrl={contract ? `/api/contracts/${contract.id}/pdf` : null}
            />
          </section>
        </main>
      )}
      <footer className="foot">
        Démonstration technique · ne constitue pas un avis de couverture · le contrat « Démo Habitation » est un document synthétique.
      </footer>
    </div>
  );
}
