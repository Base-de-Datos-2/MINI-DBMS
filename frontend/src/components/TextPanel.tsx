import { useEffect, useRef, useState } from "react";
import { useWorkspace } from "../workspaceScope";

interface Collection { table: string; column: string; id_column: string; documents: number; collection_id: string }
interface SearchResult {
  columns: { name: string }[];
  rows: unknown[][];
  total_rows: number;
  truncated: boolean;
  model: string;
  plan: { operator: string; selection: string; model: string; order: string };
  metrics: { backend_elapsed_ms: number };
}

export default function TextPanel({ token, onSql, partNumber }: {
  token: string | null; onSql: (sql: string) => void; partNumber: number;
}) {
  const { api, id: scoped } = useWorkspace();
  const [collections, setCollections] = useState<Collection[]>([]);
  const [selected, setSelected] = useState("");
  const [query, setQuery] = useState("");
  const [model, setModel] = useState<"BM25" | "TF_IDF">("BM25");
  const [useIndexes, setUseIndexes] = useState(true);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const reloadGeneration = useRef(0);
  const invalidate = () => { generation.current += 1; setResult(null); setBusy(false); setError(""); };
  const reload = async () => {
    // A refresh invalidates in-flight searches immediately, including on failure.
    invalidate();
    const requestGeneration = ++reloadGeneration.current;
    try {
      const found = await api.fetchTextTables();
      if (reloadGeneration.current !== requestGeneration) return;
      setCollections(found);
      setSelected((previous) => found.some((c) => c.table === previous) ? previous : found[0]?.table ?? "");
      setError("");
    } catch (cause) { if (reloadGeneration.current === requestGeneration) { setCollections([]); setSelected(""); setError(String(cause)); } }
  };
  useEffect(() => { void reload(); return () => { generation.current += 1; reloadGeneration.current += 1; }; }, []);
  const current = collections.find((c) => c.table === selected);
  // SQL literals are quoted independently from the selected identifier. The
  // collection and column names come exclusively from the validated registry.
  const sqlLiteral = (value: string) => `'${value.replace(/'/g, "''")}'`;
  const exampleSql = current ?
    `SELECT *, SCORE() AS relevancia FROM ${current.table} WHERE MATCH(${current.column}, ${sqlLiteral(query || "base de datos")}) USING ${model} ORDER BY relevancia DESC LIMIT 10;` : "";
  const explainSql = `EXPLAIN ${exampleSql}`;
  const sendToEditor = (sql: string) => {
    onSql(sql);
    document.getElementById(scoped("query-title"))?.scrollIntoView({ behavior: "smooth" });
  };
  const search = async () => {
    if (!current || busy || !query.trim()) return;
    const requestGeneration = ++generation.current;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const answer = await api.runTextQuery({ table: current.table, column: current.column,
        query, model, order: "score_desc", limit: 100, max_rows: 100, use_indexes: useIndexes }, token);
      if (generation.current === requestGeneration) setResult(answer);
    } catch (cause) { if (generation.current === requestGeneration) setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { if (generation.current === requestGeneration) setBusy(false); }
  };
  const numeric = (value: unknown) => typeof value === "number";
  return <section className="panel text-panel" id={scoped("text-title")} aria-labelledby={scoped("text-heading")}>
    <div className="panel-heading">
      <div>
        <h2 className="panel-title" id={scoped("text-heading")}>Búsqueda textual</h2>
        <p className="muted small panel-subtitle">
          Colecciones publicadas y selladas de la Parte {partNumber}: índice SPIMI con TF-IDF o BM25.
        </p>
      </div>
      <button type="button" className="secondary" onClick={() => void reload()}>Actualizar colecciones</button>
    </div>
    {collections.length === 0 && <p className="empty-state">No hay colecciones textuales publicadas en esta base.</p>}
    <form className="text-search" onSubmit={(event) => { event.preventDefault(); void search(); }}>
      <label className="field">Colección
        <select aria-label="Colección textual" value={selected} onChange={(event) => { setSelected(event.target.value); invalidate(); }}>
          {collections.map((c) => <option key={c.table} value={c.table}>{c.table} · {c.documents} documentos</option>)}
        </select></label>
      <label className="field">Modelo
        <select aria-label="Modelo textual" value={model} onChange={(event) => { setModel(event.target.value as "BM25" | "TF_IDF"); invalidate(); }}>
          <option value="BM25">BM25</option><option value="TF_IDF">TF-IDF + coseno</option>
        </select></label>
      <label className="field text-search-query">Consulta
        <input type="text" aria-label="Consulta textual" value={query} maxLength={4096}
          placeholder={current?.table === "productos" ? "wireless headphones" : "base de datos vectorial"}
          onChange={(event) => { setQuery(event.target.value); invalidate(); }} /></label>
      <label className="inline-field text-search-index"><input type="checkbox" checked={useIndexes} onChange={(event) => { setUseIndexes(event.target.checked); invalidate(); }}/> Usar índice</label>
      <div className="text-search-actions">
        <button type="submit" className="primary" disabled={!current || busy || !query.trim()}>{busy ? "Buscando…" : "Buscar"}</button>
        <button type="button" className="secondary" disabled={!current} onClick={() => sendToEditor(exampleSql)}>Enviar SQL al editor</button>
        <button type="button" className="secondary" disabled={!current} onClick={() => sendToEditor(explainSql)}>Ver EXPLAIN en SQL</button>
      </div>
    </form>
    {current && <div className="sql-preview"><span className="muted small">SQL equivalente ({model === "BM25" ? "BM25" : "TF-IDF"})</span><code>{exampleSql}</code></div>}
    {error && <p className="error-box" role="alert">{error}</p>}
    {result && <div className="text-results">
      <p className="text-results-summary" role="status">
        <strong>{result.total_rows} coincidencias</strong>
        <span className="chip">{result.model}</span>
        <span className="chip">{result.plan.operator}</span>
        <span className="chip">selección: {result.plan.selection}</span>
        <span className="muted small">{result.metrics.backend_elapsed_ms} ms en el servidor{result.truncated ? " · vista truncada" : ""}</span>
      </p>
      {result.rows.length === 0 ? <p className="empty-state">Ningún documento contiene esos términos.</p>
        : <div className="table-scroll"><table className="result-table"><thead><tr>{result.columns.map((c, i) => <th key={i}>{c.name}</th>)}</tr></thead>
          <tbody>{result.rows.map((row, i) => <tr key={i}>{row.map((value, j) => <td key={j} className={numeric(value) ? "numeric" : undefined}>{String(value)}</td>)}</tr>)}</tbody></table></div>}
    </div>}
  </section>;
}
