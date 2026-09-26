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
  max_csv_bytes: number;
  max_import_rows: number;
}

export interface Health {
  status: "ready" | "closing" | "unavailable" | "closed";
  mode: "read-only" | "serialized-writes";
  writes_enabled: boolean;
  database: string;
  tables: string[];
  memory_budget_bytes: number;
  limits: Limits;
  sessions: {
    open: number;
    max: number;
    idle_timeout_seconds: number;
    lock_timeout_seconds: number;
  };
}

/** One HTTP client session: a real engine SqlSession behind an opaque token. */
export interface SessionStatus {
  /** Engine session number, for display only; the token is the credential. */
  session_id: number;
  state: "IDLE" | "ACTIVE";
  transaction: {
    id: number;
    state: string;
    /** An explicit BEGIN … END group, as opposed to one implicit statement. */
    explicit: boolean;
    tables: string[];
  } | null;
  busy: boolean;
  call_elapsed_ms: number | null;
  cancel_requested: boolean;
  /** The lock the running statement is waiting for, and who holds it. */
  waiting: { resource: string; mode: "S" | "X"; blocker_ids: number[] } | null;
  expires_in_seconds: number | null;
}

export interface OpenedSession {
  token: string;
  session: SessionStatus;
}

export interface TransactionReportInfo {
  transaction_id: number;
  session_id: number;
  state: string;
  tables_touched: string[];
  tables_locked: string[];
  lock_wait_ms: number | null;
  blocker_ids: number[];
  failure_cause: string | null;
  undo: {
    bytes_captured: number;
    bytes_restored: number;
    files_captured: number;
    files_restored: number;
  } | null;
  completion_ms: number | null;
  warnings: string[];
}

export interface ExplanationInfo {
  analyzed: boolean;
  complete: boolean;
  output_rows: number | null;
  planning_ms: number | null;
  execution_ms: number | null;
  lock_wait_ms: number | null;
  transaction_id: number | null;
  transaction_state: string | null;
  error: { type: string; message: string | null } | null;
}

export interface Preset {
  label: string;
  purpose: string;
  sql: string;
}

export type Organization = "HEAP" | "SEQUENTIAL";
export type ColumnType = "INTEGER" | "FLOAT" | "BOOLEAN" | "VARCHAR";
export type IndexType = "BPLUS" | "EXTENDIBLE_HASH";
/** Declared demo fixture, or a table created from the Files panel. */
export type TableOrigin = "demo" | "csv" | "empty";

export interface TableSummary {
  id: string;
  name: string;
  organization: Organization;
  row_count: number;
  column_count: number;
  /** Indexes of this table only. */
  index_count: number;
  origin: TableOrigin;
}

export interface IndexInfo {
  name: string;
  column: string;
  type: IndexType;
  unique: boolean;
  clustered: boolean;
  supports_range: boolean;
  entry_count: number | null;
  file_bytes: number;
}

export interface TableDetail {
  id: string;
  name: string;
  organization: Organization;
  key_column: string | null;
  columns: { position: number; name: string; type: string; nullable: boolean }[];
  row_count: number;
  data_pages: number;
  file_bytes: number;
  indexes: IndexInfo[];
  origin: TableOrigin;
  source_filename: string | null;
}

/** What the server read from a CSV upload; nothing is loaded yet. */
export interface CsvPreview {
  delimiter: string;
  columns: { source: string; name: string; type: ColumnType }[];
  sample_rows: string[][];
  row_count: number;
  suggested_table_name: string;
}

export interface CreateTableRequest {
  name: string;
  organization: Organization;
  key_column: string | null;
  columns: { name: string; type: ColumnType }[];
  indexes: { column: string; type: IndexType; unique: boolean }[];
  csv?: { text: string; filename: string | null; delimiter: string | null };
}

export interface CreateTableResponse {
  request_id: string;
  mode: Health["mode"];
  table: TableDetail;
  loaded_rows: number;
  backend_elapsed_ms: number;
  session?: SessionStatus;
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

export type StatementName =
  | "SELECT"
  | "INSERT"
  | "DELETE"
  | "EXPLAIN"
  | "EXPLAIN_ANALYZE"
  | "BEGIN"
  | "END"
  | "ROLLBACK"
  | "CREATE";

export interface QueryResponse {
  request_id: string;
  mode: Health["mode"];
  statement: StatementName;
  kind: "rows" | "command" | "explanation" | "transaction" | "definition";
  columns: ResultColumn[];
  rows: unknown[][];
  returned_rows: number;
  truncated: boolean;
  truncation_reason: "row_limit" | "byte_limit" | null;
  result_complete: boolean;
  total_rows: number | null;
  affected_rows: number | null;
  /** Commands only: committed at once, or provisional inside BEGIN … END. */
  transaction?: { id: number | null; committed: boolean; provisional: boolean };
  explanation?: ExplanationInfo;
  transaction_report?: TransactionReportInfo;
  definition?: { table_name: string; primary_index_name: string | null };
  /** Control statements have no plan. */
  execution_plan: ExecutionPlan | null;
  plan_status: PlanStatus;
  metrics: {
    scope: string;
    partial: boolean;
    backend_elapsed_ms: number;
    engine: EngineMetrics | null;
  };
  /** Session state after this call, when it ran in a client session. */
  session?: SessionStatus;
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
  session?: SessionStatus;
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
