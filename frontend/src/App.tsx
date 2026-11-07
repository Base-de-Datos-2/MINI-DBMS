import { useEffect, useMemo, useState } from "react";
import { createApi, fetchHealth, fetchParts, type PartInfo } from "./api";
import Workspace from "./components/Workspace";
import { partFromHash, kindOfDatabase } from "./parts";
import { ROOT_SCOPE, WorkspaceContext, scopeFor } from "./workspaceScope";

type Layout =
  | { status: "loading" }
  | { status: "failed"; message: string }
  /** A single-part server (``python -m api --text`` …): one workspace, no tabs. */
  | { status: "single"; kind: PartInfo["kind"] }
  /** The unified server (``python -m api --all``): one tab per part. */
  | { status: "tabs"; parts: PartInfo[] };

function describeFailure(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function App() {
  const [layout, setLayout] = useState<Layout>({ status: "loading" });
  const [active, setActive] = useState<string | null>(null);
  // Tabs are mounted the first time they are opened and then kept, so each
  // part keeps its SQL, results and session while another tab is in view.
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());

  useEffect(() => {
    let current = true;
    (async () => {
      try {
        const parts = await fetchParts();
        if (!current) return;
        if (parts === null) {
          const health = await fetchHealth();
          if (current) setLayout({ status: "single", kind: kindOfDatabase(health.database) });
          return;
        }
        setLayout({ status: "tabs", parts });
      } catch (error: unknown) {
        if (current) setLayout({ status: "failed", message: describeFailure(error) });
      }
    })();
    return () => { current = false; };
  }, []);

  const parts = layout.status === "tabs" ? layout.parts : null;

  // The tab follows the address (#parte3), so a link opens the right part.
  useEffect(() => {
    if (parts === null) return;
    const follow = () => setActive(partFromHash(window.location.hash, parts));
    follow();
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, [parts]);

  useEffect(() => {
    if (active !== null && !opened.has(active)) setOpened(new Set([...opened, active]));
  }, [active, opened]);

  const scopes = useMemo(
    () => new Map((parts ?? []).filter((part) => part.base !== null)
      .map((part) => [part.id, scopeFor(createApi(part.base ?? ""), part.id)])),
    [parts],
  );

  const select = (id: string) => {
    if (window.location.hash !== `#${id}`) window.location.hash = id;
    else setActive(id);
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <h1>MINI-DBMS</h1>
          <p className="app-description">Minigestor de base de datos multimodal · Base de Datos 2</p>
        </div>
        {parts !== null && (
          <nav className="part-tabs" role="tablist" aria-label="Partes del proyecto">
            {parts.map((part) => (
              <button
                key={part.id}
                type="button"
                role="tab"
                id={`tab-${part.id}`}
                aria-selected={active === part.id}
                aria-controls={`panel-${part.id}`}
                className={`part-tab${part.status === "ready" ? "" : " missing"}`}
                onClick={() => select(part.id)}
              >
                <span className="part-number">Parte {part.number}</span>
                <span className="part-title">{part.title}</span>
              </button>
            ))}
          </nav>
        )}
      </header>

      {layout.status === "loading" && <p className="muted" role="status">Conectando con el servidor…</p>}

      {layout.status === "failed" && (
        <main className="load-error" role="alert">
          <h2>No se pudo conectar con la API</h2>
          <p>{layout.message}</p>
          <p>
            Prepara los datos con <code>python scripts/setup_all.py</code>, inicia el servidor con{" "}
            <code>python -m api --all</code> desde la raíz del repositorio y recarga la página.
          </p>
        </main>
      )}

      {layout.status === "single" && (
        <WorkspaceContext.Provider value={ROOT_SCOPE}>
          <main className="part-panel">
            <Workspace kind={layout.kind} title={null} description={null} />
          </main>
        </WorkspaceContext.Provider>
      )}

      {parts?.map((part) => {
        const scope = scopes.get(part.id);
        return (
          <main
            key={part.id}
            id={`panel-${part.id}`}
            role="tabpanel"
            aria-labelledby={`tab-${part.id}`}
            className="part-panel"
            hidden={active !== part.id}
          >
            {scope === undefined ? (
              <div className="load-error">
                <h2>Parte {part.number} · {part.title}</h2>
                <p>Esta parte no está disponible en el servidor{part.problem ? `: ${part.problem}` : "."}</p>
                {part.setup !== null && (
                  <p>Prepárala con <code>{part.setup}</code> y reinicia el servidor.</p>
                )}
              </div>
            ) : opened.has(part.id) && (
              <WorkspaceContext.Provider value={scope}>
                <Workspace kind={part.kind} title={`Parte ${part.number} · ${part.title}`} description={part.description} />
              </WorkspaceContext.Provider>
            )}
          </main>
        );
      })}
    </div>
  );
}
