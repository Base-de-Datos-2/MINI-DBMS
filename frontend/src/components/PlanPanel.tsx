import { useEffect, useState } from "react";
import type { KeyboardEvent } from "react";
import { formatBytes, formatCount, formatMs } from "../format";
import { OPERATOR_DESCRIPTIONS, indexesUsed, isRuntimeNode, splitDetails } from "../plan";
import type {
  EngineMetrics,
  ExecutionPlan,
  KeyValue,
  Outcome,
  PlanStatus,
  PreparedNode,
  RuntimeNode,
} from "../types";

interface Props {
  outcome: Outcome | null;
  busy?: boolean;
}

type View = "runtime" | "prepared";

interface PlanData {
  plan: ExecutionPlan;
  status: PlanStatus;
  metrics: EngineMetrics | null;
  partial: boolean;
}

function planData(outcome: Outcome | null): PlanData | null {
  if (outcome === null || outcome.status === "unreachable") return null;
  if (outcome.status === "success") {
    if (outcome.body.execution_plan === null) return null;
    return {
      plan: outcome.body.execution_plan,
      status: outcome.body.plan_status,
      metrics: outcome.body.metrics.engine,
      partial: outcome.body.metrics.partial,
    };
  }
  const plan = outcome.body.execution_plan;
  if (plan === undefined) return null;
  return { plan, status: outcome.body.plan_status ?? "prepared", metrics: null, partial: false };
}

const STATUS_LABELS: Record<PlanStatus, string> = {
  "execution-observed": "observado en la ejecución",
  prepared: "solo preparado, no ejecutado",
  unavailable: "no disponible",
};

function Details({ details }: { details: KeyValue[] }) {
  const { headline, rest } = splitDetails(details);
  return (
    <>
      {headline.length > 0 && (
        <div className="chips">
          {headline.map((detail) => (
            <span key={detail.key} className="chip detail-chip">
              {detail.key}: <strong>{detail.value}</strong>
            </span>
          ))}
        </div>
      )}
      {rest.length > 0 && (
        <dl className="detail-list">
          {rest.map((detail) => (
            <div key={detail.key}>
              <dt>{detail.key}</dt>
              <dd>
                <code>{detail.value}</code>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </>
  );
}

function OperatorNode({ node }: { node: RuntimeNode | PreparedNode }) {
  const runtime = isRuntimeNode(node) ? node : null;
  const description = OPERATOR_DESCRIPTIONS[node.name];
  return (
    <li className="plan-node">
      <div className="plan-node-card">
        <div className="plan-node-head">
          <span className="operator-name">{node.name}</span>
          {runtime !== null && (
            <span className="muted small">
              {formatCount(runtime.rows_examined)} → {formatCount(runtime.rows_emitted)} filas ·{" "}
              {formatMs(runtime.elapsed_ms)}
            </span>
          )}
        </div>
        {description !== undefined && <p className="muted small operator-description">{description}</p>}
        <Details details={node.details} />
        <p className="muted small">
          Salida: {node.output_columns.map((column) => column.name).join(", ") || "—"}
          {node.ordered_by !== null && ` · ordenada por ${node.ordered_by}`}
        </p>
      </div>
      {node.children.length > 0 && (
        <ul className="plan-children">
          {node.children.map((child, position) => (
            <OperatorNode key={position} node={child} />
          ))}
        </ul>
      )}
    </li>
  );
}

function Summary({ metrics, partial, root }: {
  metrics: EngineMetrics;
  partial: boolean;
  root: RuntimeNode;
}) {
  const share = metrics.memory.budget_bytes > 0
    ? Math.min(100, (100 * metrics.memory.peak_reserved_bytes) / metrics.memory.budget_bytes)
    : 0;
  const indexes = indexesUsed(root, "runtime");
  const accesses = new Set<string>();
  const collectAccesses = (node: RuntimeNode) => {
    node.details.forEach((detail) => { if (detail.key === "access") accesses.add(detail.value); });
    node.children.forEach(collectAccesses);
  };
  collectAccesses(root);
  return (
    <div className="plan-summary">
      {partial && (
        <p className="chip warn-chip">
          Métricas parciales: la vista previa cerró el resultado antes del final.
        </p>
      )}
      <p className="small">
        <span className="metric-label">Índices abiertos: </span>
        {indexes.length > 0 ? indexes.join(", ") : "sin nombres de índice declarados"}
      </p>
      {accesses.size > 0 && <p className="small"><span className="metric-label">Accesos ejecutados: </span>{[...accesses].join(", ")}</p>}
      <div className="metric">
        <span className="metric-label">Memoria reservada (pico)</span>
        <span className="metric-value">
          {formatBytes(metrics.memory.peak_reserved_bytes)} de {formatBytes(metrics.memory.budget_bytes)}
        </span>
        <div className="meter" aria-hidden="true">
          <div className="meter-fill" style={{ width: `${share}%` }} />
        </div>
      </div>
      <div className="metric">
        <span className="metric-label">Volcado a disco</span>
        <span className="metric-value">{formatBytes(metrics.temporary.bytes_spilled)}</span>
        <span className="muted small">
          pico vivo {formatBytes(metrics.temporary.peak_live_bytes)} · {metrics.temporary.peak_open_handles}{" "}
          archivos temporales abiertos (pico)
        </span>
      </div>
      <table className="io-table">
        <caption className="metric-label">Páginas de 4 KiB</caption>
        <thead>
          <tr>
            <th scope="col" />
            <th scope="col">leídas</th>
            <th scope="col">escritas</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Tablas</th>
            <td>{formatCount(metrics.pages.base_read)}</td>
            <td>{formatCount(metrics.pages.base_written)}</td>
          </tr>
          <tr>
            <th scope="row">Índices</th>
            <td>{formatCount(metrics.pages.index_read)}</td>
            <td>{formatCount(metrics.pages.index_written)}</td>
          </tr>
          <tr>
            <th scope="row">Temporales</th>
            <td>{formatCount(metrics.pages.temporary_read)}</td>
            <td>{formatCount(metrics.pages.temporary_written)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export default function PlanPanel({ outcome, busy = false }: Props) {
  const data = busy ? null : planData(outcome);
  const [view, setView] = useState<View>("runtime");
  const runtime = data?.plan.runtime ?? null;

  useEffect(() => {
    setView(runtime !== null ? "runtime" : "prepared");
  }, [runtime]);

  const changeTabWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    const choices: View[] = runtime === null ? ["prepared"] : ["runtime", "prepared"];
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current = Math.max(0, choices.indexOf(view));
    const position = event.key === "Home" ? 0
      : event.key === "End" ? choices.length - 1
        : (current + (event.key === "ArrowRight" ? 1 : choices.length - 1)) % choices.length;
    const next = choices[position];
    if (next === undefined) return;
    setView(next);
    event.currentTarget.querySelector<HTMLButtonElement>(`[data-view="${next}"]`)?.focus();
  };

  return (
    <section className="panel plan-panel" aria-labelledby="plan-title" aria-busy={busy}>
      <div className="panel-heading">
        <h2 id="plan-title" className="panel-title">
          Plan de ejecución
        </h2>
        {data !== null && (
          <div className="tabs" role="tablist" aria-label="Vista del plan" onKeyDown={changeTabWithKeyboard}>
            <button
              id="plan-runtime-tab"
              data-view="runtime"
              type="button"
              role="tab"
              aria-controls="plan-content"
              aria-selected={view === "runtime"}
              tabIndex={view === "runtime" ? 0 : -1}
              disabled={runtime === null}
              onClick={() => setView("runtime")}
            >
              Ejecutado
            </button>
            <button
              id="plan-prepared-tab"
              data-view="prepared"
              type="button"
              role="tab"
              aria-controls="plan-content"
              aria-selected={view === "prepared"}
              tabIndex={view === "prepared" ? 0 : -1}
              onClick={() => setView("prepared")}
            >
              Preparado
            </button>
          </div>
        )}
      </div>

      {data === null && (
        <p className="muted">
          {busy ? "Ejecutando… el plan de esta consulta aparecerá al finalizar."
            : outcome?.status === "success" && outcome.body.kind === "transaction"
            ? "BEGIN, END y ROLLBACK controlan la transacción: no tienen plan de ejecución."
            : "El plan aparece al ejecutar una consulta."}
        </p>
      )}

      {data !== null && (
        <p className="muted small">
          Estado del plan: {STATUS_LABELS[data.status]}. Cada operador recibe las filas de sus hijos
          (indentados debajo) y entrega su salida al operador de arriba.
        </p>
      )}

      {data !== null && <div id="plan-content" role="tabpanel" aria-labelledby={`plan-${view}-tab`} tabIndex={0}>
      {view === "runtime" && runtime !== null && (
        <>
          {data.metrics !== null && (
            <Summary metrics={data.metrics} partial={data.partial} root={runtime.root} />
          )}
          <ul className="plan-tree">
            <OperatorNode node={runtime.root} />
          </ul>
          {runtime.truncated && <p className="muted small">El árbol se recortó por su tamaño.</p>}
        </>
      )}

      {view === "prepared" && (
        <>
          <p className="muted small">
            Lo que el planner eligió antes de ejecutar. No contiene mediciones.
          </p>
          <ul className="plan-tree">
            <OperatorNode node={data.plan.prepared.root} />
          </ul>
          {data.plan.prepared.truncated && (
            <p className="muted small">El árbol se recortó por su tamaño.</p>
          )}
        </>
      )}
      </div>}
    </section>
  );
}
