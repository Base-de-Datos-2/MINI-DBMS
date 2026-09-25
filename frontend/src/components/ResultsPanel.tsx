import { completenessMessage, formatCount, formatMs, formatValue, isNumeric } from "../format";
import { commandNote, transactionFacts, transactionHeadline } from "../session";
import type { Outcome, QueryResponse } from "../types";

function ExplanationSummary({ body }: { body: QueryResponse }) {
  const info = body.explanation;
  if (info === undefined) return null;
  return (
    <div className="status-block">
      <p>
        <strong>{body.statement === "EXPLAIN_ANALYZE" ? "EXPLAIN ANALYZE" : "EXPLAIN"}</strong>:{" "}
        {info.analyzed
          ? `la consulta se ejecutó una vez y produjo ${formatCount(info.output_rows ?? 0)} filas, que se descartaron.`
          : "plan preparado; la consulta no se ejecutó."}
      </p>
      <p className="muted small">
        Planificación {formatMs(info.planning_ms ?? 0)}
        {info.execution_ms !== null && ` · ejecución ${formatMs(info.execution_ms)}`}
        {info.lock_wait_ms !== null && info.lock_wait_ms > 0 && ` · espera por locks ${formatMs(info.lock_wait_ms)}`}
        {info.transaction_id !== null && ` · transacción T${info.transaction_id} ${info.transaction_state ?? ""}`}
      </p>
      <p className="muted small">El plan está en el panel de Plan de ejecución.</p>
    </div>
  );
}

function TransactionSummary({ body }: { body: QueryResponse }) {
  const report = body.transaction_report;
  if (report === undefined) return null;
  return (
    <div className="status-block">
      <p>
        <strong>{transactionHeadline(body.statement, report)}</strong>
      </p>
      <ul className="fact-list muted small">
        {transactionFacts(report).map((fact) => (
          <li key={fact}>{fact}</li>
        ))}
      </ul>
      {body.statement === "BEGIN" && (
        <p className="muted small">
          Las sentencias siguientes de esta sesión forman un solo grupo hasta END TRANSACTION o ROLLBACK.
        </p>
      )}
    </div>
  );
}

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
            {formatCount(outcome.body.affected_rows ?? 0)} filas afectadas
            {outcome.body.transaction?.provisional === true && <span className="chip warn-chip">provisional</span>}
          </p>
          <p className="muted small">{commandNote(outcome.body)}</p>
        </div>
      )}

      {!busy && outcome?.status === "success" && outcome.body.kind === "transaction" && (
        <TransactionSummary body={outcome.body} />
      )}

      {!busy && outcome?.status === "success" && outcome.body.kind === "explanation" && (
        <ExplanationSummary body={outcome.body} />
      )}

      {!busy && outcome?.status === "success" && outcome.body.kind === "definition" && (
        <div className="status-block">
          <p>
            <strong>CREATE</strong>: tabla {outcome.body.definition?.table_name} creada.
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
