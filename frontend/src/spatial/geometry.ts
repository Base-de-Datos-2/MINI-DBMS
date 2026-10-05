import type { Coordinate, QueryResponse, SpatialPoint, SpatialTable } from "../types";

export const WIDTH = 900;
export const HEIGHT = 420;
const RADIUS = 6371008.771415059;
const radians = Math.PI / 180;

export function project(point: Coordinate, center: Coordinate, zoom: number): Coordinate {
  const scale = 256 * 2 ** zoom;
  const mercator = (latitude: number) => Math.asinh(Math.tan(latitude * radians));
  return [WIDTH / 2 + (point[1] - center[1]) / 360 * scale,
    HEIGHT / 2 - (mercator(point[0]) - mercator(center[0])) / (2 * Math.PI) * scale];
}

export function unproject(pixel: Coordinate, center: Coordinate, zoom: number): Coordinate {
  const scale = 256 * 2 ** zoom;
  const y = Math.asinh(Math.tan(center[0] * radians)) - (pixel[1] - HEIGHT / 2) / scale * 2 * Math.PI;
  return [Math.atan(Math.sinh(y)) / radians, center[1] + (pixel[0] - WIDTH / 2) / scale * 360];
}

export function inDomain(point: Coordinate, table: SpatialTable): boolean {
  return point.every(Number.isFinite) && point[0] >= table.conventions.latitude_bounds[0]
    && point[0] <= table.conventions.latitude_bounds[1]
    && point[1] >= table.conventions.longitude_bounds[0]
    && point[1] <= table.conventions.longitude_bounds[1];
}

export function previewPoints(response: QueryResponse, table: SpatialTable): SpatialPoint[] {
  const position = (name: string) => response.columns.findIndex((column) => column.name === name);
  const id = position(table.id_column), lat = position(table.latitude_column), lon = position(table.longitude_column);
  if (id < 0 || lat < 0 || lon < 0) throw new Error("La respuesta no incluye el mapeo de coordenadas registrado.");
  return response.rows.map((row) => {
    const identity = row[id];
    const latitude = row[lat], longitude = row[lon];
    if ((typeof identity !== "number" && typeof identity !== "string") || typeof latitude !== "number"
      || typeof longitude !== "number" || !inDomain([latitude, longitude], table)) {
      throw new Error("El servidor devolvió una identidad o coordenada inválida.");
    }
    return { id: identity, latitude, longitude };
  });
}

export function mergePoints(base: SpatialPoint[], hits: SpatialPoint[]): SpatialPoint[] {
  const points = new Map(base.map((point) => [String(point.id), point]));
  for (const point of hits) points.set(String(point.id), point);
  return [...points.values()];
}

export function radiusRing(center: Coordinate, metres: number, metric: "haversine" | "euclidean", origin: Coordinate): Coordinate[] {
  return Array.from({ length: 73 }, (_, index) => {
    const bearing = index / 72 * 2 * Math.PI;
    if (metric === "euclidean") return [center[0] + Math.cos(bearing) * metres / RADIUS / radians,
      center[1] + Math.sin(bearing) * metres / (RADIUS * Math.cos(origin[0] * radians)) / radians];
    const delta = metres / RADIUS, phi = center[0] * radians;
    const latitude = Math.asin(Math.sin(phi) * Math.cos(delta) + Math.cos(phi) * Math.sin(delta) * Math.cos(bearing));
    const longitude = center[1] * radians + Math.atan2(Math.sin(bearing) * Math.sin(delta) * Math.cos(phi),
      Math.cos(delta) - Math.sin(phi) * Math.sin(latitude));
    return [latitude / radians, longitude / radians];
  });
}

export function parsePolygon(text: string, table: SpatialTable): Coordinate[] {
  const points = text.trim().split(/\n+/).map((line) => {
    const parts = line.trim().split(/[\s,]+/);
    if (parts.length !== 2 || parts.some((part) => part === "")) throw new Error("Cada vértice debe tener latitud, longitud.");
    const point: Coordinate = [Number(parts[0]), Number(parts[1])];
    if (!inDomain(point, table)) throw new Error("Un vértice está fuera del dominio registrado.");
    return point;
  });
  if (points.length < 3) throw new Error("El polígono necesita al menos tres vértices.");
  return points;
}

export function spatialSql(request: SpatialRequestShape, table: SpatialTable): string {
  const metric = request.metric === "euclidean" ? ", 'euclidean'" : "";
  const distance = `distancia(${table.location_column}, mi_ubicacion${metric})`;
  return request.kind === "knn"
    ? `SELECT * FROM ${table.table} ORDER BY ${distance} LIMIT ${request.k};`
    : `SELECT * FROM ${table.table} WHERE ${distance} < ${request.radius};`;
}

interface SpatialRequestShape { kind: "radius" | "knn"; metric: "haversine" | "euclidean"; radius?: number; k?: number }
