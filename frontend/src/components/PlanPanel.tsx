import { useEffect, useState } from "react";
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
  return (
    <div className="plan-summary">
      {partial && (
        <p className="chip warn-chip">
          Métricas parciales: la vista previa cerró el resultado antes del final.
        </p>
      )}
      <p className="small">
        <span className="metric-label">Índices abiertos: </span>
        {indexes.length > 0 ? indexes.join(", ") : "ninguno (recorrido de tabla)"}
      </p>
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

export default function PlanPanel({ outcome }: Props) {
  const data = planData(outcome);
  const [view, setView] = useState<View>("runtime");
  const runtime = data?.plan.runtime ?? null;

  useEffect(() => {
    setView(runtime !== null ? "runtime" : "prepared");
  }, [runtime]);

  return (
    <section className="panel plan-panel" aria-labelledby="plan-title">
      <div className="panel-heading">
        <h2 id="plan-title" className="panel-title">
          Plan de ejecución
        </h2>
        {data !== null && (
          <div className="tabs" role="tablist" aria-label="Vista del plan">
            <button
              type="button"
              role="tab"
              aria-selected={view === "runtime"}
              disabled={runtime === null}
              onClick={() => setView("runtime")}
            >
              Ejecutado
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === "prepared"}
              onClick={() => setView("prepared")}
            >
              Preparado
            </button>
          </div>
        )}
      </div>

      {data === null && <p className="muted">El plan aparece al ejecutar una consulta.</p>}

      {data !== null && (
        <p className="muted small">
          Estado del plan: {STATUS_LABELS[data.status]}. Cada operador recibe las filas de sus hijos
          (indentados debajo) y entrega su salida al operador de arriba.
        </p>
      )}

      {data !== null && view === "runtime" && runtime !== null && (
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

      {data !== null && view === "prepared" && (
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
    </section>
  );
}
