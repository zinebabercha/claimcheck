export type Verdict = "couvert" | "non_couvert" | "incertain";

export interface Contract {
  id: string;
  name: string;
  title: string;
  source_file: string;
  pages: number;
  n_clauses: number;
  tagger: string;
}

export interface Clause {
  id: string;
  contract_id: string;
  ord: number;
  ref: string;
  chapter: string;
  article: string;
  text: string;
  page_start: number;
  page_end: number;
  is_lexicon: boolean;
  general: boolean;
  types: string[];
  perils: string[];
  topics: string[];
}

export interface Citation {
  clause_id: string;
  label: string;
  ref: string;
  page: number;
  quote: string;
  start: number;
  end: number;
  match: number;
  role: string;
}

export interface AskResult {
  verdict: Verdict;
  confidence: "haute" | "moyenne" | "faible";
  summary: string;
  reasoning: { step: string; clause_ids: string[] }[];
  citations: Citation[];
  unverified_citations: { clause_id: string; quote: string; why: string }[];
  missing_facts: string[];
  scenarios: { if: string; then: Verdict; clause_ids: string[] }[];
  limits: string;
  warnings: string[];
  trace: {
    analysis: {
      language: string;
      perils: string[];
      topics: string[];
      facts: string[];
      unknowns: string[];
      search_terms: string[];
    };
    retrieved: { clause_id: string; label: string; ref: string; reasons: string[]; score: number }[];
    timings_ms: Record<string, number>;
    model: string;
    usage: Record<string, number>;
  };
}

export interface Health {
  ok: boolean;
  llm_configured: boolean;
  model: string;
  upload: boolean;
}

export interface Meta {
  examples: string[];
  perils: string[];
  topics: string[];
}

export interface CompareGroup {
  contract_id: string;
  name: string;
  clauses: Clause[];
}
