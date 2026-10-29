import type { AskResult, Clause, CompareGroup, Contract, Health, Meta } from "./types";

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not json */
    }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => req<Health>("/api/health"),
  meta: () => req<Meta>("/api/meta"),
  contracts: () => req<Contract[]>("/api/contracts"),
  clauses: (id: string) => req<Clause[]>(`/api/contracts/${encodeURIComponent(id)}/clauses`),
  ask: (contract_id: string, question: string) =>
    req<AskResult>("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contract_id, question }),
    }),
  compare: (params: { peril?: string; topic?: string; type?: string }) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return req<CompareGroup[]>(`/api/compare?${q}`);
  },
  upload: (file: File, name: string, useLlm: boolean) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", name);
    fd.append("use_llm", String(useLlm));
    return req<Contract>("/api/contracts", { method: "POST", body: fd });
  },
};
