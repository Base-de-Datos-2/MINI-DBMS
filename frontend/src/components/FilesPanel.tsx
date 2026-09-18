import { formatBytes, plural } from "../format";
import type { IndexInfo, TableDetail, TableSummary } from "../types";

interface Props {
  tables: TableSummary[];
  selected: TableDetail | null;
  message: string | null;
  onSelect: (id: string) => void;
  onUseInQuery: (name: string) => void;
}

function organizationLabel(table: TableDetail): string {
  return table.organization === "HEAP"
    ? "Heap File"
    : `Paged Sequential File, ordenado por ${table.key_column ?? "—"}`;
}

function IndexRow({ index }: { index: IndexInfo }) {
  const flags = [
    index.type === "BPLUS" ? "B+" : "Hash extensible",
    index.clustered ? "clustered" : "unclustered",
    index.unique ? "único" : null,
    index.supports_range ? "igualdad y rango" : "solo igualdad",
  ].filter((flag): flag is string => flag !== null);
  return (
    <li className="index-row">
      <span className="index-name">{index.name}</span>
      <span className="muted"> sobre </span>
      <code>{index.column}</code>
      <div className="chips">
        {flags.map((flag) => (
          <span key={flag} className="chip">
            {flag}
          </span>
        ))}
      </div>
      <div className="muted small">
        {index.entry_count !== null && `${plural(index.entry_count, "entrada", "entradas")} · `}
        {formatBytes(index.file_bytes)}
      </div>
    </li>
  );
}

export default function FilesPanel({ tables, selected, message, onSelect, onUseInQuery }: Props) {
  return (
    <section className="panel files-panel" aria-labelledby="files-title">
      <h2 id="files-title" className="panel-title">
        Archivos
      </h2>
      {tables.length === 0 ? (
        <p className="muted">Cargando tablas del catálogo…</p>
      ) : (
        <ul className="table-list" aria-label="Tablas cargadas">
          {tables.map((table) => (
            <li key={table.id}>
              <button
                type="button"
                className={`table-button${selected?.id === table.id ? " active" : ""}`}
                aria-pressed={selected?.id === table.id}
                onClick={() => onSelect(table.id)}
              >
                <span className="table-name">{table.name}</span>
                <span className="muted small">
                  {plural(table.row_count, "fila", "filas")} ·{" "}
                  {plural(table.index_count, "índice", "índices")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {message !== null && (
        <p className="notice small" role="status">
          {message}
        </p>
      )}

      {selected !== null && (
        <div className="table-detail">
          <h3 className="detail-title">{selected.name}</h3>
          <p className="muted small">
            {organizationLabel(selected)} · {plural(selected.data_pages, "página", "páginas")} ·{" "}
            {formatBytes(selected.file_bytes)}
          </p>
          <table className="column-table">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Columna</th>
                <th scope="col">Tipo</th>
              </tr>
            </thead>
            <tbody>
              {selected.columns.map((column) => (
                <tr key={column.position}>
                  <td className="muted">{column.position}</td>
                  <td>
                    <code>{column.name}</code>
                    {column.name === selected.key_column && <span className="chip key-chip">clave</span>}
                  </td>
                  <td className="muted">{column.type}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">Ninguna columna admite NULL: el motor no lo soporta.</p>
          {selected.indexes.length > 0 ? (
            <ul className="index-list" aria-label={`Índices de ${selected.name}`}>
              {selected.indexes.map((index) => (
                <IndexRow key={index.name} index={index} />
              ))}
            </ul>
          ) : (
            <p className="muted small">Sin índices.</p>
          )}
          <button type="button" className="link-button" onClick={() => onUseInQuery(selected.name)}>
            Usar {selected.name} en la consulta
          </button>
        </div>
      )}
    </section>
  );
}
