import type {
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

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
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

export const fetchHealth = () => getJson<Health>("/api/health");
export const fetchPresets = () => getJson<Preset[]>("/api/presets");
export const fetchTables = () => getJson<TableSummary[]>("/api/tables");
export const fetchTable = (id: string) =>
  getJson<TableDetail>(`/api/tables/${encodeURIComponent(id)}`);

/**
 * Submit one statement. The outcome always carries the SQL snapshot that was
 * sent, so an edit made while the request runs can never be mislabeled.
 */
export async function runQuery(sql: string, options: QueryOptions): Promise<Outcome> {
  const started = performance.now();
  let response: Response;
  try {
    response = await fetch(`${BASE}/api/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
