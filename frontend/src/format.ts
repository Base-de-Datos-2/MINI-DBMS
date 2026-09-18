// Pure formatting helpers, kept free of React so they are unit-tested directly.

import type { Encoding, QueryResponse } from "./types";

const BYTE_UNITS = ["B", "KiB", "MiB", "GiB"] as const;

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${value.toFixed(digits)} ${BYTE_UNITS[unit]}`;
}

export function formatCount(count: number): string {
  return new Intl.NumberFormat("es-PE").format(count);
}

export function formatMs(ms: number): string {
  if (!Number.isFinite(ms)) return "—";
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 1000) return `${ms.toFixed(1)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

/** One rendered cell: its exact text plus whether it needs a visible marker. */
export interface CellText {
  text: string;
  /** Marks values that would otherwise be invisible, such as "". */
  marker: boolean;
}

/**
 * Render a value exactly as the engine produced it. int64 values beyond
 * JavaScript's precision and non-finite floats arrive as strings and are shown
 * verbatim; nothing is rounded or localized. The engine has no SQL NULL.
 */
export function formatValue(value: unknown, encoding: Encoding): CellText {
  if (encoding === "boolean") return { text: value ? "TRUE" : "FALSE", marker: false };
  if (encoding === "string" && value === "") return { text: "(cadena vacía)", marker: true };
  return { text: String(value), marker: false };
}

export function isNumeric(encoding: Encoding): boolean {
  return encoding === "int64" || encoding === "float64";
}

/** Describe preview completeness without ever presenting N as a total. */
export function completenessMessage(body: QueryResponse, maxResponseBytes: number): string {
  const shown = formatCount(body.returned_rows);
  if (!body.truncated) {
    return body.returned_rows === 0
      ? "Resultado completo y vacío: ninguna fila cumple la consulta."
      : `${shown} filas · resultado completo.`;
  }
  if (body.truncation_reason === "row_limit") {
    return `Mostrando las primeras ${shown} filas; hay más resultados (total desconocido).`;
  }
  const limit = formatBytes(maxResponseBytes);
  if (body.result_complete && body.total_rows !== null) {
    return `Mostrando ${shown} de ${formatCount(body.total_rows)} filas: se alcanzó el límite de ${limit} de la respuesta.`;
  }
  return `Mostrando ${shown} filas: se alcanzó el límite de ${limit} de la respuesta; hay más resultados (total desconocido).`;
}

/** Spanish count agreement: "1 página", "3 páginas". */
export function plural(count: number, singular: string, pluralForm: string): string {
  return `${formatCount(count)} ${count === 1 ? singular : pluralForm}`;
}
