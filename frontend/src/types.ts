// Shapes of the frozen Stage 9 contract (api/schemas.py, api/engine_service.py).
// Every field is copied from an engine object; the UI never invents plan data.

export type Encoding = "int64" | "float64" | "boolean" | "string";

export interface ResultColumn {
  position: number;
  name: string;
  type: string;
  /** int64 values beyond ±(2^53−1) and non-finite float64 arrive as strings. */
  encoding: Encoding;
}

export interface KeyValue {
  key: string;
  value: string;
}

export interface OutputColumn {
  name: string;
  type: string;
}

export interface Limits {
  default_preview_rows: number;
  max_preview_rows: number;
  max_sql_bytes: number;
  max_response_bytes: number;
}

export interface Health {
  status: "ready" | "closing" | "unavailable" | "closed";
  mode: "read-only" | "serialized-writes";
  writes_enabled: boolean;
  database: string;
  tables: string[];
  memory_budget_bytes: number;
  limits: Limits;
}

export interface Preset {
  label: string;
  purpose: string;
  sql: string;
}

export interface TableSummary {
  id: string;
  name: string;
  organization: "HEAP" | "SEQUENTIAL";
  row_count: number;
  column_count: number;
  index_count: number;
}

export interface IndexInfo {
  name: string;
  column: string;
  type: "BPLUS" | "EXTENDIBLE_HASH";
  unique: boolean;
  clustered: boolean;
  supports_range: boolean;
  entry_count: number | null;
  file_bytes: number;
}

export interface TableDetail {
  id: string;
  name: string;
  organization: "HEAP" | "SEQUENTIAL";
  key_column: string | null;
  columns: { position: number; name: string; type: string; nullable: boolean }[];
  row_count: number;
  data_pages: number;
  file_bytes: number;
  indexes: IndexInfo[];
}

/** A node of the plan the planner prepared, before anything ran. */
export interface PreparedNode {
  name: string;
  output_columns: OutputColumn[];
  details: KeyValue[];
  ordered_by: string | null;
  children: PreparedNode[];
}

/** A node of the operator tree that executed, with its local counters. */
export interface RuntimeNode extends PreparedNode {
  id: string;
  rows_examined: number;
  rows_emitted: number;
  /** Inclusive of child work: never add a parent's time to its child's. */
  elapsed_ms: number;
  children: RuntimeNode[];
}

export interface ExecutionPlan {
  prepared: { root: PreparedNode; truncated: boolean };
  runtime: { root: RuntimeNode; truncated: boolean } | null;
}

export type PlanStatus = "prepared" | "execution-observed" | "unavailable";

export interface EngineMetrics {
  rows_produced: number;
  elapsed_ms: number;
  memory: {
    budget_bytes: number;
    peak_reserved_bytes: number;
    reservations_granted: number;
    reservations_refused: number;
  };
  pages: {
    base_read: number;
    base_written: number;
    index_read: number;
    index_written: number;
    temporary_read: number;
    temporary_written: number;
  };
  temporary: {
    bytes_spilled: number;
    peak_live_bytes: number;
    live_bytes_after: number;
    peak_open_handles: number;
  };
}

export interface QueryResponse {
  request_id: string;
  mode: Health["mode"];
  statement: "SELECT" | "INSERT" | "DELETE";
  kind: "rows" | "command";
  columns: ResultColumn[];
  rows: unknown[][];
  returned_rows: number;
  truncated: boolean;
  truncation_reason: "row_limit" | "byte_limit" | null;
  result_complete: boolean;
  total_rows: number | null;
  affected_rows: number | null;
  execution_plan: ExecutionPlan;
  plan_status: PlanStatus;
  metrics: {
    scope: string;
    partial: boolean;
    backend_elapsed_ms: number;
    engine: EngineMetrics | null;
  };
}

export interface SqlLocation {
  line: number | null;
  column: number | null;
  position: number | null;
  expected: string | null;
  offending: string | null;
  context: string | null;
}

export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    request_id?: string;
    location?: SqlLocation;
    details?: Record<string, unknown>;
  };
  statement?: string;
  execution_plan?: ExecutionPlan;
  plan_status?: PlanStatus;
  mode?: string;
}

export type JoinStrategy = "AUTO" | "GRACE_HASH" | "NESTED_LOOP";

export interface QueryOptions {
  max_rows: number;
  use_indexes: boolean;
  join_strategy: JoinStrategy;
}

/** How one submitted statement ended, tied to the SQL that produced it. */
export type Outcome =
  | { status: "success"; sql: string; roundTripMs: number; body: QueryResponse }
  | { status: "error"; sql: string; roundTripMs: number; httpStatus: number; body: ErrorEnvelope }
  | { status: "unreachable"; sql: string; message: string };
