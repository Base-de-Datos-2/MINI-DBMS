import type { QueryResponse } from "./types";

/** One published Part 4 collection, as listed by GET /api/multimedia/tables. */
export interface MultimediaTable {
  table: string;
  modality: "image" | "audio";
  key_column: string;
  id_column: string;
  objects: number;
  dimension: number;
  methods: Record<string, string[]>;
  queries: string[];
  collection_id: string;
}

/** What the Results panel needs to render media for a SIMILAR_TO result. */
export interface MediaContext {
  table: string;
  modality: "image" | "audio";
  keyColumn: string;
  queryKey: string | null;
  metric: string | null;
  method: string | null;
}

const VECTOR_OPERATORS = new Set(["VectorIndexScan", "VectorScan"]);

/**
 * Media context of a row result whose plan root is a real vector scan over a
 * published collection; null for every other result. It reads the plan the
 * backend actually prepared, so a relational query on the same table shows
 * plain text.
 */
export function mediaContext(body: QueryResponse, tables: MultimediaTable[]): MediaContext | null {
  const root = body.execution_plan?.prepared.root;
  if (root === undefined || !VECTOR_OPERATORS.has(root.name)) return null;
  const detail = (key: string) => root.details.find((item) => item.key === key)?.value ?? null;
  const table = tables.find((candidate) => candidate.table === detail("table"));
  if (table === undefined) return null;
  return {
    table: table.table,
    modality: table.modality,
    keyColumn: table.key_column,
    queryKey: detail("media_key"),
    metric: detail("metric"),
    method: detail("method"),
  };
}

/** Header note for the score column: Euclidean scores are negative distances. */
export function scoreNote(metric: string | null): string | null {
  if (metric === "euclidean") return "score = −distancia euclidiana (mayor es mejor)";
  if (metric === "cosine") return "score = similitud del coseno";
  if (metric === "dot") return "score = producto punto";
  return null;
}
