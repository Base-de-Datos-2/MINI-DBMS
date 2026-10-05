import { afterEach, expect, it, vi } from "vitest";
import { fetchSpatialTables, runQuery, runSpatialQuery } from "../api";

afterEach(() => vi.unstubAllGlobals());

it("sends spatial requests with the current session token and original coordinates", async () => {
  const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ matches: [], total_rows: 0 }), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  const request = { table: "tiendas", kind: "radius" as const, center: [-12.0464, -77.0428] as [number, number], radius: 5000, metric: "haversine" as const, use_indexes: true, max_rows: 500 };
  await runSpatialQuery(request, "opaque-test-token");
  expect(fetch.mock.calls[0]?.[0]).toBe("/api/spatial/query");
  const init = (fetch.mock.calls as unknown as [string, RequestInit][])[0]?.[1];
  expect(init?.headers).toMatchObject({ "X-Session-Token": "opaque-test-token" });
  expect(JSON.parse(String(init?.body))).toEqual(request);
});

it("only includes a point parameter when the caller explicitly provides it", async () => {
  const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ kind: "rows" }), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  const options = { max_rows: 100, use_indexes: true, join_strategy: "AUTO" as const };
  await runQuery("SELECT * FROM tiendas ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10", options, "session", { mi_ubicacion: [-12, -77] });
  await runQuery("BEGIN", options, "session");
  const calls = fetch.mock.calls as unknown as [string, RequestInit][];
  expect(JSON.parse(String(calls[0]?.[1].body)).parameters).toEqual({ mi_ubicacion: [-12, -77] });
  expect(JSON.parse(String(calls[1]?.[1].body))).not.toHaveProperty("parameters");
});

it("loads registered spatial metadata through the real endpoint", async () => {
  const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response("[]", { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  await expect(fetchSpatialTables()).resolves.toEqual([]);
  expect(fetch.mock.calls[0]?.[0]).toBe("/api/spatial/tables");
});
