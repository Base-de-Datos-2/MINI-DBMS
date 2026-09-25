import { groupOpen, sessionSummary, waitingText } from "../session";
import type { SessionStatus } from "../types";

interface Props {
  status: SessionStatus | null;
  notice: string | null;
  busy: boolean;
  onRun: (sql: string) => void;
  onCancel: () => void;
  onRenew: () => void;
}

/**
 * This tab's engine session. BEGIN/END/ROLLBACK are ordinary statements sent
 * through the same /api/query path as the editor; the buttons only save typing.
 */
export default function SessionBar({ status, notice, busy, onRun, onCancel, onRenew }: Props) {
  if (status === null) {
    return <span className="mode-badge">{notice ?? "Abriendo sesión…"}</span>;
  }
  const open = groupOpen(status);
  const waiting = waitingText(status);
  return (
    <div className="session-bar" role="group" aria-label="Sesión y transacción">
      <span className="mode-badge" title="Sesión propia de esta pestaña en el motor (Etapa 8)">
        Sesión #{status.session_id}
      </span>
      <span className={`session-state${open ? " open" : ""}`} role="status">
        {sessionSummary(status)}
      </span>
      {waiting !== null && <span className="chip warn-chip">{waiting}</span>}
      {status.cancel_requested && <span className="chip warn-chip">cancelación pedida…</span>}
      <button type="button" className="secondary small-button" disabled={busy || open} onClick={() => onRun("BEGIN TRANSACTION")}>
        BEGIN
      </button>
      <button type="button" className="secondary small-button" disabled={busy || !open} onClick={() => onRun("END TRANSACTION")}>
        END
      </button>
      <button type="button" className="secondary small-button" disabled={busy || !open} onClick={() => onRun("ROLLBACK")}>
        ROLLBACK
      </button>
      {busy && (
        <button type="button" className="secondary small-button danger-button" onClick={onCancel}>
          Cancelar
        </button>
      )}
      <button
        type="button"
        className="link-button"
        disabled={busy}
        title="Cierra esta sesión (aborta su transacción abierta) y abre otra"
        onClick={onRenew}
      >
        Nueva sesión
      </button>
      {notice !== null && <span className="chip warn-chip">{notice}</span>}
    </div>
  );
}
