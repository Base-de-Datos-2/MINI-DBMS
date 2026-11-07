import type {
  OpenedSession,
  SessionStatus,
  CreateTableRequest,
  CreateTableResponse,
  CsvPreview,
  ErrorEnvelope,
  Health,
  Outcome,
  Preset,
  QueryOptions,
  QueryResponse,
  TableDetail,
  TableSummary,
  PointParameters,
  SpatialTable,
  SpatialRequest,
  SpatialResponse,
} from "./types";

/**
 * Base URL of the API. Empty means the same origin, which is how both the Vite
 * dev proxy and the backend-served build work; no machine address is baked in.
 */
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  readonly httpStatus: number;
  readonly envelope: ErrorEnvelope | null;

  constructor(httpStatus: number, envelope: ErrorEnvelope | null, message: string) {
    super(message);
    this.httpStatus = httpStatus;
    this.envelope = envelope;
  }
}

function isEnvelope(body: unknown): body is ErrorEnvelope {
  return (
    typeof body === "object" &&
    body !== null &&
    "error" in body &&
    typeof (body as { error: unknown }).error === "object"
  );
}

/** Every call of one API. ``prefix`` is the part's mount ("/parte3"), or "". */
export function createApi(prefix = "") {
  const base = `${BASE}${prefix}`;

  async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${base}${path}`, init);
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const envelope = isEnvelope(body) ? body : null;
      throw new ApiError(
        response.status,
        envelope,
        envelope?.error.message ?? `${path} respondió ${response.status}`,
      );
    }
    return body as T;
  }

  /** Header carrying the opaque session token (api/schemas.py). */
  const SESSION_HEADER = "X-Session-Token";

  const sessionHeaders = (token: string | null): Record<string, string> =>
    token === null ? {} : { [SESSION_HEADER]: token };

  const getJson = <T>(path: string, token: string | null = null) =>
    requestJson<T>(path, { headers: sessionHeaders(token) });

  const postJson = <T>(path: string, payload: unknown, token: string | null = null) =>
    requestJson<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...sessionHeaders(token) },
      body: JSON.stringify(payload),
    });

  const fetchHealth = () => getJson<Health>("/api/health");
  const fetchPresets = () => getJson<Preset[]>("/api/presets");
  const fetchTables = () => getJson<TableSummary[]>("/api/tables");
  const fetchTable = (id: string) =>
    getJson<TableDetail>(`/api/tables/${encodeURIComponent(id)}`);

  const fetchSpatialTables = () => getJson<SpatialTable[]>("/api/spatial/tables");
  const runSpatialQuery = (request: SpatialRequest, token: string | null) =>
    postJson<SpatialResponse>("/api/spatial/query", request, token);

  /** Parse a CSV on the server and infer column types; nothing is loaded. */
  const previewCsv = (text: string, filename: string | null) =>
    postJson<CsvPreview>("/api/import/preview", { text, filename });

  /** Create a table (and load its CSV rows) through the engine's own storage. */
  const createTable = (request: CreateTableRequest, token: string | null) =>
    postJson<CreateTableResponse>("/api/tables", request, token);

  /** Open one engine session; its token groups BEGIN … END across requests. */
  const openSession = () => postJson<OpenedSession>("/api/sessions", {});
  const fetchSession = (token: string) => getJson<SessionStatus>("/api/session", token);
  const cancelSession = (token: string) =>
    postJson<{ cancel_requested: boolean; session: SessionStatus }>("/api/session/cancel", {}, token);

  /**
   * Close a session: the engine aborts any open group and releases its locks.
   * `keepalive` lets the request outlive the page when the tab is closed.
   */
  function closeSession(token: string, keepalive = false): Promise<Response> {
    return fetch(`${base}/api/session`, {
      method: "DELETE",
      headers: sessionHeaders(token),
      keepalive,
    });
  }

  /**
   * Submit one statement. The outcome always carries the SQL snapshot that was
   * sent, so an edit made while the request runs can never be mislabeled.
   */
  async function runQuery(
    sql: string,
    options: QueryOptions,
    token: string | null = null,
    parameters?: PointParameters,
  ): Promise<Outcome> {
    const started = performance.now();
    let response: Response;
    try {
      response = await fetch(`${base}/api/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...sessionHeaders(token) },
        body: JSON.stringify({ sql, ...options, ...(parameters === undefined ? {} : { parameters }) }),
      });
    } catch (error: unknown) {
      return {
        status: "unreachable",
        sql,
        message: error instanceof Error ? error.message : String(error),
      };
    }
    const roundTripMs = performance.now() - started;
    const body: unknown = await response.json().catch(() => null);
    if (response.ok) {
      return { status: "success", sql, roundTripMs, body: body as QueryResponse };
    }
    const envelope: ErrorEnvelope = isEnvelope(body)
      ? body
      : { error: { code: "INTERNAL_ERROR", message: `El servidor respondió ${response.status}` } };
    return { status: "error", sql, roundTripMs, httpStatus: response.status, body: envelope };
  }

  const fetchTextTables = () => getJson<TextCollection[]>("/api/text/tables");
  const runTextQuery = (request: TextQueryRequest, token: string | null) => postJson<TextQueryResult>("/api/text/query", request, token);
  const fetchMultimediaTables = () =>
    getJson<import("./multimedia").MultimediaTable[]>("/api/multimedia/tables");

  /** URL of a registered gallery or query file; keys are encoded, never paths. */
  const mediaUrl = (table: string, key: string): string =>
    `${base}/api/multimedia/${encodeURIComponent(table)}/media/${encodeURIComponent(key)}`;

  return {
    prefix,
    fetchHealth,
    fetchPresets,
    fetchTables,
    fetchTable,
    fetchSpatialTables,
    runSpatialQuery,
    previewCsv,
    createTable,
    openSession,
    fetchSession,
    cancelSession,
    closeSession,
    runQuery,
    fetchTextTables,
    runTextQuery,
    fetchMultimediaTables,
    mediaUrl,
  };
}

export type Api = ReturnType<typeof createApi>;

/** The API at the page's own origin: a single-part server (``python -m api``). */
export const rootApi = createApi();
export const {
  fetchHealth,
  fetchPresets,
  fetchTables,
  fetchTable,
  fetchSpatialTables,
  runSpatialQuery,
  previewCsv,
  createTable,
  openSession,
  fetchSession,
  cancelSession,
  closeSession,
  runQuery,
  fetchTextTables,
  runTextQuery,
  fetchMultimediaTables,
  mediaUrl,
} = rootApi;

/** One part as listed by the unified server (``python -m api --all``). */
export interface PartInfo {
  id: string;
  number: number;
  title: string;
  description: string;
  kind: "demo" | "spatial" | "text" | "multimedia";
  base: string | null;
  status: "ready" | "missing";
  mode: string | null;
  problem: string | null;
  setup: string | null;
}

/**
 * The parts of a unified server, or null when the page is served by a
 * single-part server (it has no /api/parts route).
 */
export async function fetchParts(): Promise<PartInfo[] | null> {
  const response = await fetch(`${BASE}/api/parts`);
  if (response.status === 404) return null;
  if (!response.ok) throw new ApiError(response.status, null, `/api/parts respondió ${response.status}`);
  return (await response.json()) as PartInfo[];
}

/**
 * Hand out increasing request numbers so only the newest submission may
 * update the screen; a slow earlier response is simply ignored.
 */
export function createRequestGate() {
  let latest = 0;
  return {
    begin(): number {
      latest += 1;
      return latest;
    },
    isLatest(id: number): boolean {
      return id === latest;
    },
  };
}

export interface TextCollection { table: string; column: string; id_column: string; documents: number; collection_id: string }
export interface TextQueryRequest { table: string; column: string; query: string; model: "BM25" | "TF_IDF"; order: "score_desc" | "score_asc" | "id_asc" | "id_desc"; limit: number; max_rows: number; use_indexes: boolean }
export interface TextQueryResult { columns: { name: string }[]; rows: unknown[][]; total_rows: number; truncated: boolean; model: string; plan: { operator: string; selection: string; model: string; order: string }; metrics: { backend_elapsed_ms: number } }
