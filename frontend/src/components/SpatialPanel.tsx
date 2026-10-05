import { useEffect, useRef, useState } from "react";
import type { Coordinate, Outcome, PointParameters, QueryResponse, SpatialPoint, SpatialRequest, SpatialResponse, SpatialTable } from "../types";
import LeafletMap from "./LeafletMap";
import { inDomain, mergePoints, parsePolygon, previewPoints, radiusRing, spatialSql } from "../spatial/geometry";

interface Props {
  tables: SpatialTable[];
  metadataError: string | null;
  revision: number;
  busy: boolean;
  outcome: Outcome | null;
  onPreview: (table: string) => Promise<QueryResponse>;
  onRequest: (request: SpatialRequest) => Promise<SpatialResponse>;
  onSql: (sql: string, parameters: PointParameters) => void;
}

function failure(error: unknown): string { return error instanceof Error ? error.message : String(error); }
function defaultPolygon(origin: Coordinate): string {
  const [lat, lon] = origin;
  return [[lat - .02, lon - .02], [lat - .02, lon + .02], [lat, lon + .02],
    [lat, lon], [lat + .02, lon], [lat + .02, lon - .02]].map((point) => point.map((value) => value.toFixed(6)).join(", ")).join("\n");
}

export default function SpatialPanel({ tables, metadataError, revision, busy, outcome, onPreview, onRequest, onSql }: Props) {
  const [name, setName] = useState("");
  const table = tables.find((candidate) => candidate.table === name) ?? tables[0];
  const [center, setCenter] = useState<Coordinate>([-12.0464, -77.0428]);
  const [drawing, setDrawing] = useState(false);
  const [draft, setDraft] = useState<Coordinate[]>([]);
  const [latitude, setLatitude] = useState("-12.0464");
  const [longitude, setLongitude] = useState("-77.0428");
  const [kind, setKind] = useState<SpatialRequest["kind"]>("radius");
  const [metric, setMetric] = useState<SpatialRequest["metric"]>("haversine");
  const [radius, setRadius] = useState("5000");
  const [k, setK] = useState("10");
  const [indexes, setIndexes] = useState(true);
  const [polygon, setPolygon] = useState("");
  const [base, setBase] = useState<SpatialPoint[]>([]);
  const [response, setResponse] = useState<SpatialResponse | null>(null);
  const [snapshot, setSnapshot] = useState<SpatialRequest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const requestId = useRef(0);
  const loadedSql = useRef<{ sql: string; request: SpatialRequest } | null>(null);
  const preview = useRef(onPreview);
  preview.current = onPreview;

  const chooseCenter = (point: Coordinate) => {
    if (table === undefined || !inDomain(point, table)) {
      setError("Selecciona un centro dentro del dominio registrado.");
      return;
    }
    setCenter(point);
    setLatitude(String(point[0]));
    setLongitude(String(point[1]));
    setError(null);
  };

  useEffect(() => {
    if (table === undefined) return;
    setCenter(table.conventions.origin);
    setLatitude(String(table.conventions.origin[0]));
    setLongitude(String(table.conventions.origin[1]));
    setPolygon(defaultPolygon(table.conventions.origin));
    setMetric(table.conventions.default_metric);
    setDrawing(false); setDraft([]);
  }, [table?.table]);

  useEffect(() => {
    const id = ++requestId.current;
    setBase([]); setResponse(null); setSnapshot(null); setError(null);
    if (table === undefined) return;
    setLoading(true);
    preview.current(table.table).then((result) => {
      if (id === requestId.current) setBase(previewPoints(result, table));
    }).catch((reason: unknown) => {
      if (id === requestId.current) setError(failure(reason));
    }).finally(() => { if (id === requestId.current) setLoading(false); });
    return () => { requestId.current += 1; };
  }, [table?.table, revision, reload]);

  useEffect(() => {
    const loaded = loadedSql.current;
    if (table === undefined || outcome === null) return;
    const sqlText = outcome.sql.replace(/--[^\n]*/g, "");
    const source = /\bFROM\s+([A-Za-z_][A-Za-z_0-9]*)\b/i.exec(sqlText)?.[1];
    if (source !== table.table || !/\b(?:distancia|distance)\s*\(/i.test(sqlText)) return;
    if (outcome.status !== "success") { setResponse(null); setSnapshot(null); return; }
    if (outcome.body.kind !== "rows") return;
    try {
      const values = previewPoints(outcome.body, table);
      const request = loaded?.sql === outcome.sql && loaded.request.table === table.table ? loaded.request : null;
      setSnapshot(request);
      setError(null);
      setResponse({ table: table.table, kind: request?.kind ?? "radius", total_rows: outcome.body.total_rows,
        returned_rows: outcome.body.returned_rows, truncated: outcome.body.truncated,
        backend_elapsed_ms: outcome.body.metrics.backend_elapsed_ms,
        stats: { source: "SQL", plan: outcome.body.plan_status },
        matches: values.map((point, index) => ({ ...point, distance_metres: null,
          record: Object.fromEntries(outcome.body.columns.map((column, position) => [column.name, outcome.body.rows[index]?.[position]])) })) });
    } catch (reason: unknown) { setError(failure(reason)); setResponse(null); }
  }, [outcome, table]);

  const buildRequest = (): SpatialRequest => {
    if (table === undefined) throw new Error("No hay una tabla espacial seleccionada.");
    const point: Coordinate = [Number(latitude), Number(longitude)];
    if (latitude.trim() === "" || longitude.trim() === "" || !inDomain(point, table)) throw new Error("El centro debe tener coordenadas finitas dentro del dominio registrado.");
    const request: SpatialRequest = { table: table.table, kind, metric, use_indexes: indexes, max_rows: 500 };
    if (kind === "polygon") request.vertices = parsePolygon(polygon, table);
    else {
      request.center = point;
      if (kind === "radius") {
        const metres = Number(radius);
        if (radius.trim() === "" || !Number.isFinite(metres) || metres < 0) throw new Error("El radio debe ser un número no negativo en metros.");
        request.radius = metres;
      } else {
        const count = Number(k);
        if (k.trim() === "" || !Number.isInteger(count) || count < 0 || count > 100000) throw new Error("k debe ser un entero entre 0 y 100000.");
        request.k = count;
      }
    }
    return request;
  };

  const execute = async () => {
    const id = ++requestId.current;
    setError(null); setResponse(null); setSnapshot(null);
    try {
      const request = buildRequest();
      if (request.center !== undefined) chooseCenter(request.center);
      const result = await onRequest(request);
      if (id === requestId.current) { setResponse(result); setSnapshot(request); }
    } catch (reason: unknown) { if (id === requestId.current) setError(failure(reason)); }
  };

  const loadSql = () => {
    try {
      const request = buildRequest();
      if (table === undefined || request.kind === "polygon" || request.center === undefined) return;
      const text = spatialSql({ ...request, kind: request.kind }, table);
      loadedSql.current = { sql: text, request };
      onSql(text, { mi_ubicacion: [...request.center] });
      setError(null);
      document.getElementById("query-title")?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
    } catch (reason: unknown) { setError(failure(reason)); }
  };

  const matches = response?.matches ?? [];
  const points = mergePoints(base, matches);
  const hitIds = new Set(matches.map((point) => String(point.id)));
  const overlay = snapshot?.kind === "polygon" ? snapshot.vertices ?? []
    : snapshot?.kind === "radius" && snapshot.center !== undefined && table !== undefined
      ? radiusRing(snapshot.center, snapshot.radius ?? 0, snapshot.metric, table.conventions.origin) : [];
  const chooseOnMap = (point: Coordinate) => {
    if (drawing && kind === "polygon") {
      if (table === undefined || !inDomain(point, table)) { setError("Vértice fuera del dominio registrado."); return; }
      const vertices = [...draft, point];
      setDraft(vertices);
      setPolygon(vertices.map((vertex) => vertex.map(String).join(", ")).join("\n"));
      setError(null);
    } else chooseCenter(point);
  };

  return <section className="panel spatial-panel" aria-labelledby="spatial-title">
    <div className="panel-heading"><div><h2 className="panel-title" id="spatial-title">Explorador espacial</h2>
      <p className="muted small">Coordenadas geográficas · consultas sobre el motor R-Tree</p></div>
      <a href="#query-title">Volver al editor SQL</a></div>
    {metadataError !== null && <p role="alert" className="error-box">{metadataError}</p>}
    {table === undefined ? <p className="empty-state">No hay tablas espaciales registradas. Prepara el conjunto espacial e inicia el servidor con <code>--spatial</code>.</p>
      : <div className="spatial-layout">
        <form className="spatial-controls" onSubmit={(event) => { event.preventDefault(); void execute(); }}>
          <fieldset disabled={busy || loading}>
            <legend>Buscar puntos</legend>
            <label>Tabla espacial<select aria-label="Tabla espacial" value={table.table} onChange={(event) => setName(event.target.value)}>
              {tables.map((item) => <option key={item.table}>{item.table}</option>)}</select></label>
            <div className="spatial-fields">
              <label>Consulta<select aria-label="Consulta espacial" value={kind} onChange={(event) => setKind(event.target.value as SpatialRequest["kind"])}>
                <option value="radius">Radio</option><option value="knn">k vecinos</option><option value="polygon">Polígono</option></select></label>
              <label>Métrica<select aria-label="Métrica espacial" value={metric} disabled={kind === "polygon"} onChange={(event) => setMetric(event.target.value as SpatialRequest["metric"])}>
                <option value="haversine">Haversine</option><option value="euclidean">Euclidiana local</option></select></label>
              {kind !== "polygon" && <><label>Latitud<input aria-label="Latitud del centro" type="number" step="any" value={latitude} onChange={(event) => setLatitude(event.target.value)} /></label>
                <label>Longitud<input aria-label="Longitud del centro" type="number" step="any" value={longitude} onChange={(event) => setLongitude(event.target.value)} /></label></>}
              {kind === "radius" && <label>Radio (metros)<input aria-label="Radio en metros" type="number" min="0" step="any" value={radius} onChange={(event) => setRadius(event.target.value)} /></label>}
              {kind === "knn" && <label>Vecinos (k)<input aria-label="Vecinos k" type="number" min="0" max="100000" value={k} onChange={(event) => setK(event.target.value)} /></label>}
            </div>
            {kind === "polygon" && <label>Vértices: latitud, longitud<textarea aria-label="Vértices del polígono" rows={6} value={polygon} onChange={(event) => { setPolygon(event.target.value); setDraft([]); setDrawing(false); }} />
              <span className="muted small">Un par por línea. El contorno incluye su frontera; el motor valida que sea simple.</span></label>}
            {kind === "polygon" && <div className="polygon-drawing">
              <label className="inline-field"><input type="checkbox" checked={drawing} onChange={(event) => { setDrawing(event.target.checked); if (event.target.checked) { setDraft([]); setPolygon(""); } }} />Dibujar vértices con clics en el mapa</label>
              <button type="button" onClick={() => { setDraft([]); setPolygon(""); }}>Limpiar vértices</button>
              <p className="muted small">Marca al menos tres vértices y pulsa Buscar en el mapa. El motor valida y cierra el contorno.</p>
            </div>}
            <label className="inline-field"><input type="checkbox" checked={indexes} onChange={(event) => setIndexes(event.target.checked)} />Usar R-Tree</label>
            <button className="primary" type="submit">{busy ? "Consultando…" : "Buscar en el mapa"}</button>
            {kind !== "polygon" && <button type="button" onClick={loadSql}>Cargar consulta en SQL</button>}
          </fieldset>
          <p className="muted small">Latitud [{table.conventions.latitude_bounds.join(", ")}]; longitud [{table.conventions.longitude_bounds.join(", ")}]. Distancias en metros. Euclidiana usa un plano local fijo.</p>
        </form>
        <div className="spatial-map">
          <div className="map-toolbar"><button type="button" disabled={busy || loading} onClick={() => setReload((value) => value + 1)}>Actualizar puntos</button></div>
          <LeafletMap table={table} points={points} hitIds={hitIds} center={center} overlay={overlay}
            draft={kind === "polygon" ? draft : []} busy={busy || loading} onChoose={chooseOnMap} />
          <div className="map-legend"><span>Puntos almacenados</span><span>Resultados en verde</span><span>Centro en rojo</span></div>
          <p className="muted small">Leaflet + OpenStreetMap · calles y referencias reales. Clic o Enter para elegir el centro; arrastra y usa + / − para zoom. La cartografía requiere Internet. Los marcadores son registros de tu motor; pulsa uno para ver su nombre y coordenadas.</p>
          <p className="small" role="status">{loading ? "Cargando puntos almacenados…" : `Vista previa: ${base.length} de ${table.row_count} puntos almacenados (máximo 500), más resultados recibidos.`}</p>
        </div>
        <div className="spatial-results">
          {error !== null && <p className="error-box" role="alert">{error}</p>}
          {response === null ? <p className="muted small">Envía una búsqueda para resaltar coincidencias reales. Editar los controles no cambia el resultado de la última consulta.</p>
            : <><p role="status"><strong>{response.total_rows === null ? "Total de coincidencias desconocido" : `${response.total_rows} coincidencias`}</strong> · {response.returned_rows} mostradas · {response.backend_elapsed_ms.toFixed(2)} ms en el servidor</p>
              <p className="muted small">{snapshot === null ? "Consulta SQL: revisa la sentencia y el plan de ejecución" : snapshot.kind === "polygon" ? "Polígono con frontera incluida" : `${snapshot.metric} · centro ${snapshot.center?.join(", ")}`} · {Object.entries(response.stats).map(([key, value]) => `${key}: ${value}`).join(" · ")}</p>
              {response.truncated && <p className="warning">Resultado limitado por filas o bytes. Solo se resaltan las coincidencias recibidas.</p>}
              {matches.length === 0 ? <p className="empty-state">No se encontraron puntos para esta búsqueda.</p>
                : <div className="table-scroll"><table><thead><tr><th>ID</th><th>Latitud</th><th>Longitud</th><th>Distancia (m)</th><th>Registro</th></tr></thead>
                  <tbody>{matches.map((point) => <tr key={String(point.id)}><td>{point.id}</td><td>{point.latitude.toFixed(6)}</td><td>{point.longitude.toFixed(6)}</td><td>{point.distance_metres === null ? snapshot?.kind === "polygon" ? "No aplica" : "No proyectada" : point.distance_metres.toFixed(3)}</td><td>{Object.entries(point.record).map(([key, value]) => `${key}: ${String(value)}`).join(" · ")}</td></tr>)}</tbody></table></div>}</>}
        </div>
      </div>}
  </section>;
}
