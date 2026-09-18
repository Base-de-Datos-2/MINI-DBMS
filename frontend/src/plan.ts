import type { KeyValue, PreparedNode, RuntimeNode } from "./types";

/**
 * Generic, static descriptions of each physical operator. They explain what an
 * operator *is*; everything specific to a query comes from the engine report.
 */
export const OPERATOR_DESCRIPTIONS: Record<string, string> = {
  TableScan: "Recorre todas las filas vivas de un archivo de datos.",
  IndexScan: "Localiza filas a través de un índice B+ o Extendible Hashing.",
  Filter: "Conserva solo las filas que cumplen el predicado.",
  Projection: "Selecciona y ordena las columnas de salida.",
  ExternalSort: "Ordenamiento externo: runs ordenados en disco y mezcla k-way.",
  ExternalHashGroup: "Agrupación por hashing externo con particiones en disco.",
  GraceHashJoin: "Join por hashing externo: particiona ambas entradas en disco.",
  NestedLoopJoin: "Join de referencia por bucle anidado sobre una entrada volcada.",
  IndexNestedLoopJoin: "Join que sondea un índice de la tabla interna por cada fila.",
  IndexOrderedGroup: "Agrupación recorriendo un índice B+ en orden.",
  Insert: "Inserción de filas con mantenimiento de índices.",
  Delete: "Borrado de filas con mantenimiento de índices.",
};

/**
 * Detail keys that describe the access path or measured external work. They
 * are surfaced first; every other detail is still shown, never hidden.
 */
const HEADLINE_KEYS = new Set([
  "relation",
  "access",
  "index",
  "index_name",
  "strategy",
  "bounds",
  "key",
  "initial_runs",
  "merge_passes",
  "fan_in",
  "partitions",
  "repartitions",
  "sorted_fallbacks",
  "partition_pairs",
  "build_overflows",
  "nested_loop_fallbacks",
  "index_probes",
  "inner_passes",
]);

export function splitDetails(details: KeyValue[]): { headline: KeyValue[]; rest: KeyValue[] } {
  return {
    headline: details.filter((detail) => HEADLINE_KEYS.has(detail.key)),
    rest: details.filter((detail) => !HEADLINE_KEYS.has(detail.key)),
  };
}

/**
 * Collect the persisted index names a plan names. The two plans spell this
 * differently: a prepared plan stores the index name under `index`, while an
 * executed operator stores its adapter class under `index` and the persisted
 * name under `index_name`. Reading the right key avoids guessing.
 */
export function indexesUsed(
  root: RuntimeNode | PreparedNode,
  source: "runtime" | "prepared",
): string[] {
  const key = source === "runtime" ? "index_name" : "index";
  const found = new Set<string>();
  const visit = (node: RuntimeNode | PreparedNode) => {
    for (const detail of node.details) {
      if (detail.key === key) found.add(detail.value);
    }
    node.children.forEach(visit);
  };
  visit(root);
  return [...found];
}

/** Executed operators carry measured counters; prepared ones never do. */
export function isRuntimeNode(node: RuntimeNode | PreparedNode): node is RuntimeNode {
  return "rows_emitted" in node;
}
