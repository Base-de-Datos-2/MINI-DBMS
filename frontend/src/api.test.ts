import { afterEach, describe, expect, it, vi } from "vitest";
import { createRequestGate, runQuery } from "./api";

const OPTIONS = { max_rows: 100, use_indexes: true, join_strategy: "AUTO" as const };

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("runQuery", () => {
  it("returns a success outcome tied to the SQL that was sent", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, { kind: "rows", rows: [[1]] })));

    const outcome = await runQuery("SELECT 1", OPTIONS);

    expect(outcome.status).toBe("success");
    expect(outcome.sql).toBe("SELECT 1");
  });

  it("keeps the structured error envelope and HTTP status", async () => {
    const envelope = { error: { code: "ENGINE_BUSY", message: "ocupado", request_id: "x" } };
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(409, envelope)));

    const outcome = await runQuery("SELECT 1", OPTIONS);

    expect(outcome.status).toBe("error");
    if (outcome.status === "error") {
      expect(outcome.httpStatus).toBe(409);
      expect(outcome.body.error.code).toBe("ENGINE_BUSY");
    }
  });

  it("reports an unreachable server instead of throwing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }));

    const outcome = await runQuery("SELECT 1", OPTIONS);

    expect(outcome).toEqual({ status: "unreachable", sql: "SELECT 1", message: "Failed to fetch" });
  });

  it("wraps a non-JSON failure in an internal-error envelope", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 502 })));

    const outcome = await runQuery("SELECT 1", OPTIONS);

    expect(outcome.status).toBe("error");
    if (outcome.status === "error") expect(outcome.body.error.code).toBe("INTERNAL_ERROR");
  });
});

describe("createRequestGate", () => {
  it("lets only the newest request update the screen", () => {
    const gate = createRequestGate();
    const first = gate.begin();
    const second = gate.begin();

    expect(gate.isLatest(first)).toBe(false);
    expect(gate.isLatest(second)).toBe(true);
  });
});
