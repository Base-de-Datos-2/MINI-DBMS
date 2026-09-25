// Plain-language descriptions of session and transaction state, free of React.
// Every fact comes from the server's session status or engine reports.

import { formatBytes, formatMs } from "./format";
import type { QueryResponse, SessionStatus, StatementName, TransactionReportInfo } from "./types";

const STATE_LABELS: Record<string, string> = {
  ACTIVE: "activa",
  COMMITTING: "confirmándose",
  COMMITTED: "confirmada",
  ABORTING: "abortándose",
  ABORTED: "abortada",
  ABORT_FAILED: "falló el rollback",
};

export const stateLabel = (state: string): string => STATE_LABELS[state] ?? state;

/** True while this session holds an explicit BEGIN … END group. */
export function groupOpen(status: SessionStatus | null): boolean {
  return status?.transaction?.explicit === true;
}

export function sessionSummary(status: SessionStatus): string {
  const transaction = status.transaction;
  if (transaction === null) return status.busy ? "Ejecutando" : "Sin transacción abierta";
  const tables = transaction.tables.length > 0 ? ` · locks: ${transaction.tables.join(", ")}` : "";
  if (transaction.explicit) {
    return `Transacción T${transaction.id} ${stateLabel(transaction.state)}${tables}`;
  }
  return `Sentencia en curso (transacción implícita T${transaction.id})${tables}`;
}

/** "Esperando lock S sobre enrollments, retenido por T6 · 2.3 s" or null. */
export function waitingText(status: SessionStatus): string | null {
  const wait = status.waiting;
  if (wait === null) return null;
  const holders = wait.blocker_ids.map((id) => `T${id}`).join(", ");
  const elapsed = status.call_elapsed_ms === null ? "" : ` · ${formatMs(status.call_elapsed_ms)}`;
  return `Esperando lock ${wait.mode} sobre ${wait.resource}${holders ? `, retenido por ${holders}` : ""}${elapsed}`;
}

const CONTROL_TITLES: Partial<Record<StatementName, string>> = {
  BEGIN: "BEGIN TRANSACTION",
  END: "END TRANSACTION",
  ROLLBACK: "ROLLBACK",
};

export function transactionHeadline(statement: StatementName, report: TransactionReportInfo): string {
  const title = CONTROL_TITLES[statement] ?? statement;
  return `${title}: transacción T${report.transaction_id} ${stateLabel(report.state)}.`;
}

/** Measured facts of a finished group; undo is before-image copying, not recovery. */
export function transactionFacts(report: TransactionReportInfo): string[] {
  const facts: string[] = [];
  if (report.tables_touched.length > 0) facts.push(`Tablas modificadas: ${report.tables_touched.join(", ")}`);
  if (report.undo !== null && report.undo.bytes_captured > 0) {
    facts.push(`Imagen previa (undo) copiada: ${formatBytes(report.undo.bytes_captured)}`);
  }
  if (report.undo !== null && report.undo.bytes_restored > 0) {
    facts.push(`Restaurado desde la imagen previa: ${formatBytes(report.undo.bytes_restored)}`);
  }
  if (report.lock_wait_ms !== null && report.lock_wait_ms > 0) {
    facts.push(`Espera por locks: ${formatMs(report.lock_wait_ms)}`);
  }
  if (report.blocker_ids.length > 0) {
    facts.push(`Esperó a: ${report.blocker_ids.map((id) => `T${id}`).join(", ")}`);
  }
  if (report.completion_ms !== null) facts.push(`Cierre del grupo: ${formatMs(report.completion_ms)}`);
  if (report.failure_cause !== null) facts.push(`Causa: ${report.failure_cause}`);
  return [...facts, ...report.warnings.map((warning) => `Aviso: ${warning}`)];
}

/** How a command's row count should be read: final or provisional. */
export function commandNote(body: QueryResponse): string {
  const transaction = body.transaction;
  if (transaction === undefined || transaction.id === null) return "Ejecutado una sola vez.";
  if (transaction.provisional) {
    return `Provisional: pertenece a la transacción T${transaction.id} y solo se confirma con END TRANSACTION.`;
  }
  return `Confirmado como transacción implícita T${transaction.id}.`;
}

/** What an error did to the session's transaction, from the error details. */
export function failureNote(details: Record<string, unknown> | undefined): string | null {
  if (details === undefined) return null;
  const transaction = details.transaction as { id?: number; state?: string } | undefined;
  if (details.group_aborted === true) {
    const id = transaction?.id !== undefined ? ` T${transaction.id}` : "";
    return `La transacción${id} se abortó completa: todos sus cambios se deshicieron y sus locks se liberaron.`;
  }
  if (transaction?.state === "ABORTED") {
    return `La sentencia se ejecutó como transacción T${transaction.id} y se abortó: no se confirmó nada.`;
  }
  return null;
}
