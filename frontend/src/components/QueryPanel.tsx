import type { KeyboardEvent } from "react";
import { failureNote } from "../session";
import type { JoinStrategy, Outcome, Preset, QueryOptions } from "../types";

interface Props {
  sql: string;
  onSqlChange: (sql: string) => void;
  presets: Preset[];
  options: QueryOptions;
  maxPreviewRows: number;
  onOptionsChange: (options: QueryOptions) => void;
  busy: boolean;
  outcome: Outcome | null;
  onExecute: () => void;
}

const JOIN_LABELS: Record<JoinStrategy, string> = {
  AUTO: "Automático (planner)",
  GRACE_HASH: "Forzar Grace hash join",
  NESTED_LOOP: "Forzar nested loop",
};

const ERROR_TITLES: Record<string, string> = {
  SQL_ERROR: "Consulta inválida",
  STATEMENT_DISABLED: "Sentencia deshabilitada en este modo",
  ENGINE_BUSY: "Motor ocupado",
  ENGINE_UNAVAILABLE: "Motor no disponible",
  EXECUTION_REFUSED: "El motor rechazó la ejecución",
  RESULT_TOO_LARGE: "Resultado demasiado grande",
  REQUEST_TOO_LARGE: "Consulta demasiado grande",
  INVALID_REQUEST: "Petición inválida",
  INTERNAL_ERROR: "Error interno del servidor",
  SESSION_BUSY: "La sesión ya está ejecutando otra petición",
  SESSION_NOT_FOUND: "La sesión expiró o se cerró",
  SESSION_LIMIT: "Demasiadas sesiones abiertas",
  TRANSACTION_PROTOCOL: "Orden de transacción inválido",
  TRANSACTION_ABORTED: "Transacción abortada",
  TRANSACTION_CANCELLED: "Transacción cancelada",
  LOCK_TIMEOUT: "Tiempo de espera de lock agotado",
};

function Diagnostics({ outcome }: { outcome: Outcome | null }) {
  if (outcome === null || outcome.status === "success") return null;
  if (outcome.status === "unreachable") {
    return (
      <div className="error-box" role="alert">
        <p className="error-type">No se pudo contactar con el servidor</p>
        <p className="small">{outcome.message}. Comprueba que `python -m api` siga en ejecución.</p>
      </div>
    );
  }
  const { error } = outcome.body;
  const location = error.location;
  const details = error.details;
  return (
    <div className="error-box" role="alert">
      <p className="error-type">
        {ERROR_TITLES[error.code] ?? error.code} <span className="muted small">({error.code})</span>
      </p>
      {location !== undefined && location.line !== null && location.column !== null && (
        <p className="small">
          Línea {location.line}, columna {location.column}
          {location.expected ? ` · se esperaba ${location.expected}` : ""}
          {location.offending ? ` · se encontró ${location.offending}` : ""}
        </p>
      )}
      {location?.context && <pre className="error-context">{location.context}</pre>}
      <p className="error-message">{error.message}</p>
      {failureNote(details) !== null && <p className="error-message"><strong>{failureNote(details)}</strong></p>}
      {details !== undefined && (
        <pre className="error-context">{JSON.stringify(details, null, 2)}</pre>
      )}
      {error.request_id !== undefined && (
        <p className="muted small">request_id {error.request_id}</p>
      )}
    </div>
  );
}

export default function QueryPanel({
  sql,
  onSqlChange,
  presets,
  options,
  maxPreviewRows,
  onOptionsChange,
  busy,
  outcome,
  onExecute,
}: Props) {
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      onExecute();
    }
  };

  return (
    <section className="panel query-panel" aria-labelledby="query-title">
      <div className="panel-heading">
        <h2 id="query-title" className="panel-title">
          Consulta
        </h2>
        <label className="inline-field">
          <span className="muted small">Presets</span>
          <select
            aria-label="Presets"
            value=""
            onChange={(event) => {
              if (event.target.value !== "") onSqlChange(event.target.value);
            }}
          >
            <option value="">Elegir…</option>
            {presets.map((preset) => (
              <option key={preset.label} value={preset.sql} title={preset.purpose}>
                {preset.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <textarea
        className="sql-editor"
        aria-label="Editor SQL"
        value={sql}
        spellCheck={false}
        onChange={(event) => onSqlChange(event.target.value)}
        onKeyDown={onKeyDown}
      />

      <div className="toolbar">
        <label className="inline-field" title="Pasa use_indexes al planner; cambia lo que se ejecuta">
          <input
            type="checkbox"
            aria-label="Usar índices"
            checked={options.use_indexes}
            onChange={(event) => onOptionsChange({ ...options, use_indexes: event.target.checked })}
          />
          <span>Usar índices</span>
        </label>
        <label className="inline-field">
          <span>Join</span>
          <select
            aria-label="Estrategia de join"
            value={options.join_strategy}
            onChange={(event) =>
              onOptionsChange({ ...options, join_strategy: event.target.value as JoinStrategy })
            }
          >
            {(Object.keys(JOIN_LABELS) as JoinStrategy[]).map((strategy) => (
              <option key={strategy} value={strategy}>
                {JOIN_LABELS[strategy]}
              </option>
            ))}
          </select>
        </label>
        <label className="inline-field">
          <span>Filas a mostrar</span>
          <input
            type="number"
            aria-label="Filas a mostrar"
            min={0}
            max={maxPreviewRows}
            value={options.max_rows}
            onChange={(event) => {
              const requested = Math.trunc(Number(event.target.value) || 0);
              const max_rows = Math.min(maxPreviewRows, Math.max(0, requested));
              onOptionsChange({ ...options, max_rows });
            }}
          />
        </label>
        <span className="toolbar-spacer" />
        <button type="button" className="primary" disabled={busy} onClick={onExecute}>
          {busy ? "Ejecutando…" : "Ejecutar"}
        </button>
      </div>
      <p className="muted small">Ctrl + Enter ejecuta. Cada envío se ejecuta una sola vez.</p>
      <Diagnostics outcome={outcome} />
    </section>
  );
}
