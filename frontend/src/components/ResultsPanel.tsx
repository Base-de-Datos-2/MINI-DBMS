import { completenessMessage, formatCount, formatMs, formatValue, isNumeric } from "../format";
import type { Outcome } from "../types";

interface Props {
  outcome: Outcome | null;
  busy: boolean;
  maxResponseBytes: number;
}

export default function ResultsPanel({ outcome, busy, maxResponseBytes }: Props) {
  return (
    <section className="panel results-panel" aria-labelledby="results-title" aria-busy={busy}>
      <h2 id="results-title" className="panel-title">
        Resultados
      </h2>

      {busy && <p className="muted">Ejecutando…</p>}
      {!busy && outcome === null && <p className="muted">Ejecuta una consulta para ver sus filas.</p>}

      {!busy && outcome !== null && outcome.status !== "success" && (
        // Never keep an earlier success on screen as if it answered this query.
        <p className="muted">
          Sin resultados: la última consulta no se completó. El detalle está en el panel de Consulta.
        </p>
      )}

      {!busy && outcome?.status === "success" && outcome.body.kind === "command" && (
        <div className="status-block">
          <p>
            <strong>{outcome.body.statement}</strong>:{" "}
            {formatCount(outcome.body.affected_rows ?? 0)} filas afectadas.
          </p>
          <p className="muted small">
            Ejecutado una sola vez, sin transacción ni rollback (Etapa 8 pendiente).
          </p>
        </div>
      )}

      {!busy && outcome?.status === "success" && outcome.body.kind === "rows" && (
        <>
          <div className="status-block">
            <p className="status-line">
              {completenessMessage(outcome.body, maxResponseBytes)}
              {outcome.body.truncated && <span className="chip warn-chip">vista previa</span>}
            </p>
            <p className="muted small">
              Backend {formatMs(outcome.body.metrics.backend_elapsed_ms)} (prepare → cierre del cursor) ·
              ida y vuelta del navegador {formatMs(outcome.roundTripMs)} · request_id{" "}
              {outcome.body.request_id.slice(0, 8)}
            </p>
            <p className="muted small submitted-sql" title="SQL que produjo este resultado">
              {outcome.sql}
            </p>
          </div>
          {outcome.body.columns.length > 0 && (
            <div className="table-scroll">
              <table className="result-table">
                <thead>
                  <tr>
                    {outcome.body.columns.map((column) => (
                      <th key={column.position} scope="col">
                        {column.name}
                        <span className="column-type">{column.type}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {outcome.body.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {outcome.body.columns.map((column) => {
                        const cell = formatValue(row[column.position], column.encoding);
                        const classes = [
                          isNumeric(column.encoding) ? "numeric" : "",
                          cell.marker ? "marker" : "",
                        ].join(" ").trim();
                        return (
                          <td key={column.position} className={classes || undefined}>
                            {cell.text}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
