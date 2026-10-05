import { describe, expect, it } from "vitest";
import { inDomain, mergePoints, parsePolygon, previewPoints, project, radiusRing, spatialSql, unproject } from "./geometry";
import type { Coordinate, QueryResponse, SpatialTable } from "../types";

const table: SpatialTable = { table: "tiendas", location_column: "ubicacion", id_column: "id", latitude_column: "latitud", longitude_column: "longitud", row_count: 9,
  conventions: { origin: [-12.0464, -77.0428], latitude_bounds: [-12.3, -11.8], longitude_bounds: [-77.25, -76.75], point_order: "latitude,longitude", default_metric: "haversine", distance_unit: "metres" } };

describe("geographic map contracts", () => {
  it("keeps longitude on the horizontal axis and latitude increasing northward", () => {
    const center = table.conventions.origin;
    expect(project(center, center, 10)).toEqual([450, 210]);
    expect(project([center[0], center[1] + .01], center, 10)[0]).toBeGreaterThan(450);
    expect(project([center[0] + .01, center[1]], center, 10)[1]).toBeLessThan(210);
  });
  it("roundtrips click coordinates across different zoom levels", () => {
    const point: Coordinate = [-12.12, -77.12];
    for (const zoom of [7, 10, 17]) {
      const restored = unproject(project(point, table.conventions.origin, zoom), table.conventions.origin, zoom);
      expect(restored[0]).toBeCloseTo(point[0], 10);
      expect(restored[1]).toBeCloseTo(point[1], 10);
    }
  });
  it("merges hits outside the preview and retains separate identities at the same location", () => {
    const base = [{ id: "9007199254740993", latitude: -12, longitude: -77 }, { id: 2, latitude: -12, longitude: -77 }];
    const merged = mergePoints(base, [{ id: "9007199254740993", latitude: -12.1, longitude: -77 }, { id: 3, latitude: -12, longitude: -77 }]);
    expect(merged.map((point) => String(point.id))).toEqual(["9007199254740993", "2", "3"]);
    expect(merged[0]?.latitude).toBe(-12.1);
  });
  it("validates finite coordinates and includes exact domain boundaries", () => {
    expect(inDomain([-12.3, -77.25], table)).toBe(true);
    expect(inDomain([NaN, -77], table)).toBe(false);
    expect(inDomain([-77, -12], table)).toBe(false);
  });
  it("rejects incomplete and out-of-domain polygons before sending", () => {
    expect(() => parsePolygon("-12,-77\n-12.1,-77", table)).toThrow("tres");
    expect(() => parsePolygon("-12,-77\n-12.1,-77\n0,0", table)).toThrow("dominio");
    expect(parsePolygon("-12,-77\n-12.1,-77\n-12.1,-77.1", table)).toHaveLength(3);
  });
  it("reads the registered columns without guessing their order and preserves int64 strings", () => {
    const response = { columns: [{ name: "longitud" }, { name: "id" }, { name: "latitud" }], rows: [[-77, "9007199254740993", -12]] } as QueryResponse;
    expect(previewPoints(response, table)).toEqual([{ id: "9007199254740993", latitude: -12, longitude: -77 }]);
    expect(() => previewPoints({ ...response, columns: [] }, table)).toThrow("mapeo");
  });
  it("uses typed mi_ubicacion instead of interpolated coordinates in SQL", () => {
    expect(spatialSql({ kind: "radius", metric: "haversine", radius: 5000 }, table)).toBe("SELECT * FROM tiendas WHERE distancia(ubicacion, mi_ubicacion) < 5000;");
    expect(spatialSql({ kind: "knn", metric: "euclidean", k: 10 }, table)).toContain("distancia(ubicacion, mi_ubicacion, 'euclidean') LIMIT 10");
  });
  it("draws radius rings in metres in both metrics, with a closed contour", () => {
    for (const metric of ["haversine", "euclidean"] as const) {
      const ring = radiusRing(table.conventions.origin, 5000, metric, table.conventions.origin);
      expect(ring).toHaveLength(73);
      expect(ring[0]?.[0]).toBeCloseTo(-12.0464 + 5000 / 6371008.771415059 * 180 / Math.PI, 7);
      expect(ring[0]?.[1]).toBeCloseTo(ring[72]?.[1] ?? 0, 8);
    }
  });
});
