import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  createRequestGate,
  fetchHealth,
  fetchPresets,
  fetchTable,
  fetchTables,
  runQuery,
} from "./api";
import FilesPanel from "./components/FilesPanel";
import PlanPanel from "./components/PlanPanel";
import QueryPanel from "./components/QueryPanel";
import ResultsPanel from "./components/ResultsPanel";
import type {
  Health,
  Outcome,
  Preset,
  QueryOptions,
  TableDetail,
  TableSummary,
} from "./types";

function describeFailure(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [tables, setTables] = useState<TableSummary[]>([]);
  const [selected, setSelected] = useState<TableDetail | null>(null);
  const [filesMessage, setFilesMessage] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sql, setSql] = useState("");
  const [options, setOptions] = useState<QueryOptions>({
    max_rows: 100,
    use_indexes: true,
    join_strategy: "AUTO",
  });
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState(false);
  const gate = useRef(createRequestGate());

  const selectTable = useCallback(async (id: string) => {
    try {
      setSelected(await fetchTable(id));
      setFilesMessage(null);
    } catch (error: unknown) {
      setFilesMessage(describeFailure(error));
    }
  }, []);

  const loadTables = useCallback(async (): Promise<TableSummary[]> => {
    const loaded = await fetchTables();
    setTables(loaded);
    return loaded;
  }, []);

  useEffect(() => {
    // Health and presets never touch the engine, so they load together. Table
    // metadata does, so it follows sequentially rather than competing for the
    // single engine admission.
    (async () => {
      try {
        const [loadedHealth, loadedPresets] = await Promise.all([fetchHealth(), fetchPresets()]);
        setHealth(loadedHealth);
        setPresets(loadedPresets);
        const first = loadedPresets[0];
        if (first !== undefined) setSql(first.sql);
        const loadedTables = await loadTables();
        const firstTable = loadedTables[0];
        if (firstTable !== undefined) await selectTable(firstTable.id);
      } catch (error: unknown) {
        setLoadError(describeFailure(error));
      }
    })();
  }, [loadTables, selectTable]);

  const execute = useCallback(async () => {
    if (busy || sql.trim() === "") return;
    const requestNumber = gate.current.begin();
    setBusy(true);
    try {
      const next = await runQuery(sql, options);
      // Only the newest submission may replace what is on screen.
      if (!gate.current.isLatest(requestNumber)) return;
      setOutcome(next);
      if (next.status === "success" && next.body.kind === "command") {
        await loadTables();
        if (selected !== null) await selectTable(selected.id);
      }
    } finally {
      if (gate.current.isLatest(requestNumber)) setBusy(false);
    }
  }, [busy, sql, options, loadTables, selectTable, selected]);

  const modeLabel =
    health?.mode === "serialized-writes"
      ? "Escrituras serializadas · Transacciones pendientes"
      : "Solo lectura · Transacciones pendientes";

  return (
    <div className="app">
      <header className="app-header">
        <h1>MINI-DBMS</h1>
        {health !== null && (
          <>
            <span className="mode-badge" title="Etapa 8 (transacciones) aún pendiente">
              {modeLabel}
            </span>
            {health.status !== "ready" && (
              <span className="mode-badge danger">Motor {health.status}</span>
            )}
          </>
        )}
      </header>

      {loadError !== null ? (
        <main className="load-error" role="alert">
          <h2>No se pudo conectar con la API</h2>
          <p>{loadError}</p>
          <p>
            Inicia el servidor con <code>python -m api</code> desde la raíz del repositorio y
            recarga la página.
          </p>
        </main>
      ) : (
        <main className="workspace">
          <FilesPanel
            tables={tables}
            selected={selected}
            message={filesMessage}
            onSelect={(id) => void selectTable(id)}
            onUseInQuery={(name) => setSql(`SELECT * FROM ${name};`)}
          />
          <QueryPanel
            sql={sql}
            onSqlChange={setSql}
            presets={presets}
            options={options}
            maxPreviewRows={health?.limits.max_preview_rows ?? 500}
            onOptionsChange={setOptions}
            busy={busy}
            outcome={outcome}
            onExecute={() => void execute()}
          />
          <ResultsPanel
            outcome={outcome}
            busy={busy}
            maxResponseBytes={health?.limits.max_response_bytes ?? 1024 * 1024}
          />
          <PlanPanel outcome={outcome} />
        </main>
      )}
    </div>
  );
}
