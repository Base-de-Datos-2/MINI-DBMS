import { describe, expect, it } from "vitest";
import {
  commandNote,
  failureNote,
  groupOpen,
  sessionSummary,
  transactionFacts,
  transactionHeadline,
  waitingText,
} from "./session";
import type { QueryResponse, SessionStatus, TransactionReportInfo } from "./types";

const idle: SessionStatus = {
  session_id: 3,
  state: "IDLE",
  transaction: null,
  busy: false,
  call_elapsed_ms: null,
  cancel_requested: false,
  waiting: null,
  expires_in_seconds: 300,
};

const inGroup: SessionStatus = {
  ...idle,
  state: "ACTIVE",
  transaction: { id: 7, state: "ACTIVE", explicit: true, tables: ["enrollments"] },
};

const report: TransactionReportInfo = {
  transaction_id: 7,
  session_id: 3,
  state: "COMMITTED",
  tables_touched: ["enrollments"],
  tables_locked: ["enrollments"],
  lock_wait_ms: 0,
  blocker_ids: [],
  failure_cause: null,
  undo: { bytes_captured: 8212, bytes_restored: 0, files_captured: 1, files_restored: 0 },
  completion_ms: 9.2,
  warnings: [],
};

describe("session descriptions", () => {
  it("tell an idle session from an open group", () => {
    expect(sessionSummary(idle)).toBe("Sin transacción abierta");
    expect(groupOpen(idle)).toBe(false);
    expect(sessionSummary(inGroup)).toBe("Transacción T7 activa · locks: enrollments");
    expect(groupOpen(inGroup)).toBe(true);
  });

  it("name the lock a statement waits for and who holds it", () => {
    const waiting: SessionStatus = {
      ...inGroup,
      busy: true,
      call_elapsed_ms: 2300,
      waiting: { resource: "students", mode: "S", blocker_ids: [6] },
    };
    expect(waitingText(waiting)).toBe("Esperando lock S sobre students, retenido por T6 · 2.30 s");
    expect(waitingText(idle)).toBeNull();
  });

  it("report a finished group with its measured undo traffic", () => {
    expect(transactionHeadline("END", report)).toBe("END TRANSACTION: transacción T7 confirmada.");
    expect(transactionFacts(report)).toEqual([
      "Tablas modificadas: enrollments",
      "Imagen previa (undo) copiada: 8.0 KiB",
      "Cierre del grupo: 9.2 ms",
    ]);
  });

  it("never present a provisional count as committed", () => {
    const body = { transaction: { id: 7, committed: false, provisional: true } } as QueryResponse;
    expect(commandNote(body)).toMatch(/^Provisional: .*T7.*END TRANSACTION/);
    const done = { transaction: { id: 8, committed: true, provisional: false } } as QueryResponse;
    expect(commandNote(done)).toBe("Confirmado como transacción implícita T8.");
  });

  it("explain what an error did to the transaction", () => {
    expect(failureNote({ group_aborted: true, transaction: { id: 7, state: "ABORTED" } })).toMatch(
      /T7 se abortó completa/,
    );
    expect(failureNote({ transaction: { id: 9, state: "ABORTED" } })).toMatch(/T9 y se abortó/);
    expect(failureNote(undefined)).toBeNull();
  });
});
