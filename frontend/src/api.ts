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

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
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
export const SESSION_HEADER = "X-Session-Token";

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

export const fetchHealth = () => getJson<Health>("/api/health");
export const fetchPresets = () => getJson<Preset[]>("/api/presets");
export const fetchTables = () => getJson<TableSummary[]>("/api/tables");
export const fetchTable = (id: string) =>
  getJson<TableDetail>(`/api/tables/${encodeURIComponent(id)}`);

/** Parse a CSV on the server and infer column types; nothing is loaded. */
export const previewCsv = (text: string, filename: string | null) =>
  postJson<CsvPreview>("/api/import/preview", { text, filename });

/** Create a table (and load its CSV rows) through the engine's own storage. */
export const createTable = (request: CreateTableRequest, token: string | null) =>
  postJson<CreateTableResponse>("/api/tables", request, token);

/** Open one engine session; its token groups BEGIN … END across requests. */
export const openSession = () => postJson<OpenedSession>("/api/sessions", {});
export const fetchSession = (token: string) => getJson<SessionStatus>("/api/session", token);
export const cancelSession = (token: string) =>
  postJson<{ cancel_requested: boolean; session: SessionStatus }>("/api/session/cancel", {}, token);

/**
 * Close a session: the engine aborts any open group and releases its locks.
 * `keepalive` lets the request outlive the page when the tab is closed.
 */
export function closeSession(token: string, keepalive = false): Promise<Response> {
  return fetch(`${BASE}/api/session`, {
    method: "DELETE",
    headers: sessionHeaders(token),
    keepalive,
  });
}

/**
 * Submit one statement. The outcome always carries the SQL snapshot that was
 * sent, so an edit made while the request runs can never be mislabeled.
 */
export async function runQuery(
  sql: string,
  options: QueryOptions,
  token: string | null = null,
): Promise<Outcome> {
  const started = performance.now();
  let response: Response;
  try {
    response = await fetch(`${BASE}/api/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...sessionHeaders(token) },
      body: JSON.stringify({ sql, ...options }),
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
