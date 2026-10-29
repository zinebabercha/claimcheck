import type { Verdict } from "./types";

export const VERDICT_LABEL: Record<Verdict, string> = {
  couvert: "Couvert",
  non_couvert: "Non couvert",
  incertain: "Incertain",
};

export const PERIL_LABEL: Record<string, string> = {
  incendie: "Incendie",
  degats_eaux: "Dégâts des eaux",
  tempete: "Tempête / grêle",
  vol: "Vol",
  bris_vitrage: "Bris de vitrage",
  rc: "Responsabilité civile",
  catnat: "Catastrophe naturelle",
};

export const TOPIC_LABEL: Record<string, string> = {
  parties_communes: "Parties communes",
  dependances: "Dépendances",
  exterieur: "Extérieur / jardin",
  velo: "Vélo",
  objets_valeur: "Objets de valeur",
  electronique: "Électronique",
  batiment: "Bâtiment",
  vehicule: "Véhicule",
  inoccupation: "Absence / inoccupation",
  franchise_plafond: "Franchise / plafond",
};

export const TYPE_LABEL: Record<string, string> = {
  garantie: "Garantie",
  exclusion: "Exclusion",
  condition: "Condition",
  obligation: "Obligation",
  definition: "Définition",
  champ: "Champ",
  autre: "Autre",
};

export const label = (map: Record<string, string>, k: string) => map[k] ?? k;
