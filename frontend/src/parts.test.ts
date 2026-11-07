import { afterEach, describe, expect, it, vi } from "vitest";
import { createApi, fetchParts, type PartInfo } from "./api";
import { kindOfDatabase, partFromHash } from "./parts";

const part = (id: string, status: PartInfo["status"] = "ready"): PartInfo => ({
  id, number: Number(id.slice(-1)), title: id, description: "", kind: "demo",
  base: status === "ready" ? `/${id}` : null, status, mode: null, problem: null, setup: null,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("part tabs", () => {
  it("opens the tab named by the address, else the first ready part", () => {
    const parts = [part("parte1", "missing"), part("parte2"), part("parte3")];
    expect(partFromHash("#parte3", parts)).toBe("parte3");
    expect(partFromHash("#parte1", parts)).toBe("parte1");
    expect(partFromHash("", parts)).toBe("parte2");
    expect(partFromHash("#otra", parts)).toBe("parte2");
    expect(partFromHash("", [])).toBeNull();
  });

  it("maps a single-part server to its panels", () => {
    expect(kindOfDatabase("spatial")).toBe("spatial");
    expect(kindOfDatabase("text")).toBe("text");
    expect(kindOfDatabase("multimedia")).toBe("multimedia");
    expect(kindOfDatabase("demo")).toBe("demo");
  });

  it("sends every call of a part to its own prefix", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      calls.push(url);
      return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    const api = createApi("/parte3");
    await api.fetchTextTables();
    await api.runQuery("SELECT 1", { max_rows: 1, use_indexes: true, join_strategy: "AUTO" });
    expect(calls).toEqual(["/parte3/api/text/tables", "/parte3/api/query"]);
  });

  it("recognizes a single-part server by its missing /api/parts route", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
    expect(await fetchParts()).toBeNull();
  });
});
