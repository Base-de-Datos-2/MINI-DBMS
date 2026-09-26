import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  cancelSession,
  closeSession,
  createRequestGate,
  fetchHealth,
  fetchPresets,
  fetchSession,
  fetchTable,
  fetchTables,
  openSession,
  runQuery,
} from "./api";
import CreateTableDialog from "./components/CreateTableDialog";
import FilesPanel from "./components/FilesPanel";
import PlanPanel from "./components/PlanPanel";
import QueryPanel from "./components/QueryPanel";
import ResultsPanel from "./components/ResultsPanel";
import SessionBar from "./components/SessionBar";
import { groupOpen } from "./session";
import type {
  CreateTableResponse,
  Health,
  Outcome,
  Preset,
  QueryOptions,
  SessionStatus,
  TableDetail,
  TableSummary,
} from "./types";

function describeFailure(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

/** While a statement runs, refresh the session so lock waits are visible. */
const SESSION_POLL_MS = 400;

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
  const [creating, setCreating] = useState(false);
  const [session, setSession] = useState<SessionStatus | null>(null);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);
  // The token is a credential for this tab's engine session: kept in memory
  // only, never rendered, and closed when the page goes away.
  const token = useRef<string | null>(null);
  const gate = useRef(createRequestGate());
  // React StrictMode runs effects twice in development; the initial load
  // (and its session) must still happen once.
  const loadStarted = useRef(false);

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

  const startSession = useCallback(async () => {
    try {
      const opened = await openSession();
      token.current = opened.token;
      setSession(opened.session);
    } catch (error: unknown) {
      token.current = null;
      setSession(null);
      setSessionNotice(`Sin sesión: ${describeFailure(error)}`);
    }
  }, []);

  useEffect(() => {
    if (loadStarted.current) return;
    loadStarted.current = true;
    (async () => {
      try {
        const [loadedHealth, loadedPresets] = await Promise.all([fetchHealth(), fetchPresets()]);
        setHealth(loadedHealth);
        setPresets(loadedPresets);
        const first = loadedPresets[0];
        if (first !== undefined) setSql(first.sql);
        await startSession();
        const loadedTables = await loadTables();
        const firstTable = loadedTables[0];
        if (firstTable !== undefined) await selectTable(firstTable.id);
      } catch (error: unknown) {
        setLoadError(describeFailure(error));
      }
    })();
  }, [loadTables, selectTable, startSession]);

  // Closing the tab closes its session: the engine aborts an open group and
  // releases its locks instead of holding them until the idle timeout.
  useEffect(() => {
    const onPageHide = () => {
      if (token.current !== null) void closeSession(token.current, true).catch(() => undefined);
    };
    window.addEventListener("pagehide", onPageHide);
    return () => window.removeEventListener("pagehide", onPageHide);
  }, []);

  useEffect(() => {
    if (!busy || token.current === null) return;
    const current = token.current;
    const timer = window.setInterval(() => {
      fetchSession(current)
        .then((status) => {
          if (token.current === current) setSession(status);
        })
        .catch(() => undefined);
    }, SESSION_POLL_MS);
    return () => window.clearInterval(timer);
  }, [busy]);

  const run = useCallback(
    async (text: string) => {
      if (busy || text.trim() === "") return;
      const requestNumber = gate.current.begin();
      setBusy(true);
      setSessionNotice(null);
      try {
        const next = await runQuery(text, options, token.current);
        const status = next.status === "unreachable" ? undefined : next.body.session;
        if (status !== undefined) setSession(status);
        // Only the newest submission may replace what is on screen.
        if (!gate.current.isLatest(requestNumber)) return;
        setOutcome(next);
        if (next.status === "error" && next.body.error.code === "SESSION_NOT_FOUND") {
          // Never replay the statement: open a fresh session and say why.
          await startSession();
          setSessionNotice(
            "La sesión anterior expiró o se cerró (su transacción abierta se abortó). Se abrió una nueva; vuelve a enviar la sentencia si quieres.",
          );
          return;
        }
        const changedData =
          next.status === "success" &&
          (next.body.kind === "command" ||
            (next.body.kind === "transaction" && next.body.statement !== "BEGIN"));
        const aborted =
          next.status === "error" && next.body.error.details?.group_aborted === true;
        if (changedData || aborted) {
          await loadTables();
          if (selected !== null) await selectTable(selected.id);
        }
      } finally {
        if (gate.current.isLatest(requestNumber)) setBusy(false);
      }
    },
    [busy, options, loadTables, selectTable, selected, startSession],
  );

  const cancel = useCallback(async () => {
    if (token.current === null) return;
    try {
      const answer = await cancelSession(token.current);
      setSession(answer.session);
    } catch (error: unknown) {
      setSessionNotice(describeFailure(error));
    }
  }, []);

  const renewSession = useCallback(async () => {
    if (token.current !== null) {
      await closeSession(token.current).catch(() => undefined);
      token.current = null;
    }
    setSessionNotice(null);
    await startSession();
    await loadTables().catch(() => undefined);
  }, [loadTables, startSession]);

  const tableCreated = useCallback(
    async (created: CreateTableResponse) => {
      setCreating(false);
      if (created.session !== undefined) setSession(created.session);
      const name = created.table.name;
      setSql(`SELECT * FROM ${name};`);
      try {
        await loadTables();
      } catch (error: unknown) {
        setFilesMessage(describeFailure(error));
        return;
      }
      setSelected(created.table);
      setFilesMessage(
        created.table.origin === "csv"
          ? `Tabla «${name}» creada con ${created.loaded_rows} filas importadas.`
          : `Tabla «${name}» creada.`,
      );
    },
    [loadTables],
  );

  const writesEnabled = health?.writes_enabled === true && health.status === "ready";

  return (
    <div className="app">
      <header className="app-header">
        <h1>MINI-DBMS</h1>
        {health !== null && (
          <>
            <span
              className="mode-badge"
              title="Política del servidor: sin --allow-writes solo se aceptan SELECT, EXPLAIN y el control de transacciones"
            >
              {health.mode === "serialized-writes" ? "Escrituras habilitadas" : "Solo lectura"}
            </span>
            {health.status !== "ready" && (
              <span className="mode-badge danger">Motor {health.status}</span>
            )}
            <SessionBar
              status={session}
              notice={sessionNotice}
              busy={busy}
              onRun={(text) => void run(text)}
              onCancel={() => void cancel()}
              onRenew={() => void renewSession()}
            />
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
            canCreate={writesEnabled && !groupOpen(session) && !busy}
            createHint={
              !writesEnabled
                ? "Crear tablas es una escritura: arranca el servidor con --allow-writes"
                : groupOpen(session)
                  ? "Termina la transacción abierta (END o ROLLBACK) antes de crear una tabla"
                  : "Importar un CSV o definir una tabla nueva"
            }
            onCreate={() => setCreating(true)}
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
            onExecute={() => void run(sql)}
          />
          <ResultsPanel
            outcome={outcome}
            busy={busy}
            maxResponseBytes={health?.limits.max_response_bytes ?? 1024 * 1024}
          />
          <PlanPanel outcome={outcome} />
        </main>
      )}

      {creating && health !== null && (
        <CreateTableDialog
          existingTables={tables.map((table) => table.name)}
          limits={health.limits}
          token={token.current}
          onClose={() => setCreating(false)}
          onCreated={(created) => void tableCreated(created)}
        />
      )}
    </div>
  );
}
