import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, createTable, previewCsv } from "../api";
import { formatBytes, formatCount, plural } from "../format";
import {
  COLUMN_TYPES,
  INDEX_LABELS,
  draftFromPreview,
  emptyDraft,
  problems,
  removeColumn,
  renameColumn,
  toRequest,
  withOrganization,
} from "../tableDraft";
import type { TableDraft } from "../tableDraft";
import type { ColumnType, CreateTableResponse, CsvPreview, IndexType, Limits } from "../types";

interface Props {
  existingTables: string[];
  limits: Limits;
  /** This tab's session: the CREATE runs in it, not in a shared one. */
  token: string | null;
  onClose: () => void;
  onCreated: (created: CreateTableResponse) => void;
}

type Source = "csv" | "empty";

interface Upload {
  filename: string;
  text: string;
  preview: CsvPreview;
}

interface Failure {
  title: string;
  message: string;
  where: string | null;
}

const MAX_COLUMNS = 32;
const MAX_INDEXES = 8;

const DELIMITER_LABELS: Record<string, string> = {
  ",": "coma",
  ";": "punto y coma",
  "\t": "tabulador",
  "|": "barra",
};

const ERROR_TITLES: Record<string, string> = {
  CSV_ERROR: "El CSV no se pudo cargar",
  DEFINITION_ERROR: "Definición inválida",
  TABLE_EXISTS: "La tabla ya existe",
  TRANSACTION_PROTOCOL: "Hay una transacción abierta",
  LOCK_TIMEOUT: "Otra transacción retiene el esquema",
  SESSION_NOT_FOUND: "La sesión expiró",
  WRITES_DISABLED: "Escrituras deshabilitadas",
  ENGINE_BUSY: "Motor ocupado",
  ENGINE_UNAVAILABLE: "Motor no disponible",
  REQUEST_TOO_LARGE: "Archivo demasiado grande",
  INVALID_REQUEST: "Petición inválida",
  INTERNAL_ERROR: "Error interno del servidor",
};

function describeFailure(error: unknown): Failure {
  if (error instanceof ApiError && error.envelope !== null) {
    const { code, message, details } = error.envelope.error;
    const line = typeof details?.line === "number" ? `línea ${details.line}` : null;
    const column = typeof details?.column === "string" ? `columna «${details.column}»` : null;
    const where = [line, column].filter((part): part is string => part !== null).join(", ");
    return { title: ERROR_TITLES[code] ?? code, message, where: where || null };
  }
  const message = error instanceof Error ? error.message : String(error);
  return { title: "No se pudo contactar con el servidor", message, where: null };
}

export default function CreateTableDialog({ existingTables, limits, token, onClose, onCreated }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const failureBox = useRef<HTMLDivElement>(null);
  const [source, setSource] = useState<Source>("csv");
  const [upload, setUpload] = useState<Upload | null>(null);
  const [draft, setDraft] = useState<TableDraft>(emptyDraft);
  const [phase, setPhase] = useState<"idle" | "reading" | "creating">("idle");
  const [failure, setFailure] = useState<Failure | null>(null);
  const working = phase !== "idle";

  useEffect(() => {
    const node = dialog.current;
    if (node !== null && !node.open) node.showModal();
  }, []);

  // The dialog scrolls; bring a new error into view next to the actions.
  useEffect(() => {
    if (failure !== null) failureBox.current?.scrollIntoView({ block: "nearest" });
  }, [failure]);

  const hints = [
    ...(source === "csv" && upload === null ? ["Elige un archivo CSV."] : []),
    ...(source === "empty" || upload !== null ? problems(draft, existingTables) : []),
  ];

  async function chooseFile(file: File) {
    setFailure(null);
    if (file.size > limits.max_csv_bytes) {
      setUpload(null);
      setFailure({
        title: "Archivo demasiado grande",
        message: `${file.name} pesa ${formatBytes(file.size)}; el límite es ${formatBytes(limits.max_csv_bytes)}.`,
        where: null,
      });
      return;
    }
    setPhase("reading");
    try {
      const text = await file.text();
      const preview = await previewCsv(text, file.name);
      setUpload({ filename: file.name, text, preview });
      setDraft(draftFromPreview(preview));
    } catch (error: unknown) {
      setUpload(null);
      setFailure(describeFailure(error));
    } finally {
      setPhase("idle");
    }
  }

  function switchSource(next: Source) {
    setSource(next);
    setFailure(null);
    setDraft(next === "csv" && upload !== null ? draftFromPreview(upload.preview) : emptyDraft());
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (working || hints.length > 0) return;
    setPhase("creating");
    setFailure(null);
    const csv =
      source === "csv" && upload !== null
        ? { text: upload.text, filename: upload.filename, delimiter: upload.preview.delimiter }
        : null;
    try {
      onCreated(await createTable(toRequest(draft, csv), token));
    } catch (error: unknown) {
      setFailure(describeFailure(error));
      setPhase("idle");
    }
  }

  const setColumnType = (position: number, type: ColumnType) =>
    setDraft({
      ...draft,
      columns: draft.columns.map((column, index) => (index === position ? { ...column, type } : column)),
    });

  const setIndex = (position: number, change: Partial<TableDraft["indexes"][number]>) =>
    setDraft({
      ...draft,
      indexes: draft.indexes.map((index, at) => (at === position ? { ...index, ...change } : index)),
    });

  const clustered = draft.organization === "SEQUENTIAL" ? draft.indexes[0] : undefined;
  const showDefinition = source === "empty" || upload !== null;
  const rowCount = upload?.preview.row_count ?? 0;

  return (
    <dialog
      ref={dialog}
      className="dialog"
      aria-labelledby="create-table-title"
      onCancel={(event) => {
        if (working) event.preventDefault();
      }}
      onClose={onClose}
    >
      <form onSubmit={(event) => void submit(event)}>
        <div className="panel-heading">
          <h2 id="create-table-title" className="dialog-title">
            Nueva tabla
          </h2>
          <div className="tabs" role="tablist" aria-label="Origen de la tabla">
            <button
              type="button"
              role="tab"
              aria-selected={source === "csv"}
              disabled={working}
              onClick={() => switchSource("csv")}
            >
              Importar CSV
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={source === "empty"}
              disabled={working}
              onClick={() => switchSource("empty")}
            >
              Definir columnas
            </button>
          </div>
        </div>

        {source === "csv" && (
          <div className="dialog-section">
            <label className="field">
              <span>Archivo CSV (la primera fila es la cabecera)</span>
              <input
                type="file"
                accept=".csv,.tsv,.txt,text/csv"
                disabled={working}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file !== undefined) void chooseFile(file);
                }}
              />
            </label>
            <p className="muted small">
              Hasta {formatCount(limits.max_import_rows)} filas y {formatBytes(limits.max_csv_bytes)}. Los tipos se
              infieren de todos los valores; el motor no tiene NULL, así que una celda vacía solo cabe en VARCHAR.
            </p>
            {phase === "reading" && <p className="muted">Leyendo el archivo…</p>}
            {upload !== null && (
              <div className="table-scroll sample">
                <table className="result-table">
                  <caption className="muted small">
                    {upload.filename}: {plural(upload.preview.row_count, "fila", "filas")} · separador{" "}
                    {DELIMITER_LABELS[upload.preview.delimiter] ?? upload.preview.delimiter} · primeras{" "}
                    {upload.preview.sample_rows.length}
                  </caption>
                  <thead>
                    <tr>
                      {upload.preview.columns.map((column, position) => (
                        <th key={position} scope="col">
                          {column.source}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {upload.preview.sample_rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {row.map((cell, position) => (
                          <td key={position}>{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {showDefinition && (
          <>
            <div className="dialog-section">
              <label className="field">
                <span>Nombre de la tabla</span>
                <input
                  type="text"
                  value={draft.name}
                  disabled={working}
                  spellCheck={false}
                  onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                />
              </label>
            </div>

            <fieldset className="dialog-section" disabled={working}>
              <legend>Columnas</legend>
              <table className="column-table editor-table">
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    {source === "csv" && <th scope="col">Cabecera CSV</th>}
                    <th scope="col">Nombre</th>
                    <th scope="col">Tipo</th>
                    {source === "empty" && <th scope="col" aria-label="Quitar" />}
                  </tr>
                </thead>
                <tbody>
                  {draft.columns.map((column, position) => (
                    <tr key={position}>
                      <td className="muted">{position}</td>
                      {source === "csv" && <td className="muted">{column.source}</td>}
                      <td>
                        <input
                          type="text"
                          aria-label={`Nombre de la columna ${position}`}
                          value={column.name}
                          spellCheck={false}
                          onChange={(event) => setDraft(renameColumn(draft, position, event.target.value))}
                        />
                      </td>
                      <td>
                        <select
                          aria-label={`Tipo de la columna ${position}`}
                          value={column.type}
                          onChange={(event) => setColumnType(position, event.target.value as ColumnType)}
                        >
                          {COLUMN_TYPES.map((type) => (
                            <option key={type} value={type}>
                              {type}
                            </option>
                          ))}
                        </select>
                      </td>
                      {source === "empty" && (
                        <td>
                          <button
                            type="button"
                            className="link-button"
                            disabled={draft.columns.length === 1}
                            onClick={() => setDraft(removeColumn(draft, position))}
                          >
                            Quitar
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
              {source === "empty" && draft.columns.length < MAX_COLUMNS && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      columns: [...draft.columns, { name: `col${draft.columns.length + 1}`, type: "VARCHAR" }],
                    })
                  }
                >
                  Añadir columna
                </button>
              )}
            </fieldset>

            <fieldset className="dialog-section" disabled={working}>
              <legend>Organización del archivo</legend>
              <label className="inline-field">
                <input
                  type="radio"
                  name="organization"
                  checked={draft.organization === "HEAP"}
                  onChange={() => setDraft(withOrganization(draft, "HEAP"))}
                />
                <span>Heap File (orden de llegada)</span>
              </label>
              <label className="inline-field">
                <input
                  type="radio"
                  name="organization"
                  checked={draft.organization === "SEQUENTIAL"}
                  onChange={() => setDraft(withOrganization(draft, "SEQUENTIAL"))}
                />
                <span>Paged Sequential File (ordenado por clave)</span>
              </label>
              {draft.organization === "SEQUENTIAL" && (
                <label className="inline-field">
                  <span>Clave</span>
                  <select
                    aria-label="Columna clave"
                    value={draft.keyColumn ?? ""}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        keyColumn: event.target.value,
                        indexes: draft.indexes.map((index) => ({ ...index, column: event.target.value })),
                      })
                    }
                  >
                    {draft.columns.map((column, position) => (
                      <option key={position} value={column.name}>
                        {column.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </fieldset>

            <fieldset className="dialog-section" disabled={working}>
              <legend>Índices</legend>
              {draft.organization === "SEQUENTIAL" ? (
                <>
                  <label className="inline-field">
                    <input
                      type="checkbox"
                      checked={clustered !== undefined}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          indexes: event.target.checked
                            ? [{ column: draft.keyColumn ?? "", type: "BPLUS", unique: false }]
                            : [],
                        })
                      }
                    />
                    <span>B+ clustered sobre la clave</span>
                  </label>
                  {clustered !== undefined && (
                    <label className="inline-field">
                      <input
                        type="checkbox"
                        checked={clustered.unique}
                        onChange={(event) => setIndex(0, { unique: event.target.checked })}
                      />
                      <span>clave única (rechaza duplicados)</span>
                    </label>
                  )}
                  <p className="muted small">
                    Un Paged Sequential File solo admite el B+ clustered sobre su clave. Hash extensible y B+
                    unclustered requieren Heap File.
                  </p>
                </>
              ) : (
                <>
                  {draft.indexes.length === 0 && <p className="muted small">Sin índices: se usará TableScan.</p>}
                  {draft.indexes.map((index, position) => (
                    <div key={position} className="index-editor">
                      <select
                        aria-label={`Columna del índice ${position + 1}`}
                        value={index.column}
                        onChange={(event) => setIndex(position, { column: event.target.value })}
                      >
                        {draft.columns.map((column, at) => (
                          <option key={at} value={column.name}>
                            {column.name}
                          </option>
                        ))}
                      </select>
                      <select
                        aria-label={`Tipo del índice ${position + 1}`}
                        value={index.type}
                        onChange={(event) => setIndex(position, { type: event.target.value as IndexType })}
                      >
                        {(Object.keys(INDEX_LABELS) as IndexType[]).map((type) => (
                          <option key={type} value={type}>
                            {INDEX_LABELS[type]}
                          </option>
                        ))}
                      </select>
                      <label className="inline-field">
                        <input
                          type="checkbox"
                          checked={index.unique}
                          onChange={(event) => setIndex(position, { unique: event.target.checked })}
                        />
                        <span>único</span>
                      </label>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() =>
                          setDraft({ ...draft, indexes: draft.indexes.filter((_, at) => at !== position) })
                        }
                      >
                        Quitar
                      </button>
                    </div>
                  ))}
                  {draft.indexes.length < MAX_INDEXES && draft.columns.length > 0 && (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() =>
                        setDraft({
                          ...draft,
                          indexes: [
                            ...draft.indexes,
                            { column: draft.columns[0]?.name ?? "", type: "BPLUS", unique: false },
                          ],
                        })
                      }
                    >
                      Añadir índice
                    </button>
                  )}
                  <p className="muted small">
                    B+ admite igualdad y rango; Hash extensible solo igualdad. Cada índice se construye desde el
                    archivo de datos al crear la tabla.
                  </p>
                </>
              )}
            </fieldset>
          </>
        )}

        {hints.length > 0 && showDefinition && (
          <ul className="hint-list small">
            {hints.map((hint) => (
              <li key={hint}>{hint}</li>
            ))}
          </ul>
        )}

        {failure !== null && (
          <div className="error-box" role="alert" ref={failureBox}>
            <p className="error-type">{failure.title}</p>
            {failure.where !== null && <p className="small">En {failure.where}</p>}
            <p className="error-message">{failure.message}</p>
          </div>
        )}

        {phase === "creating" && (
          <p className="muted" role="status">
            Creando la tabla… el motor inserta fila por fila y construye cada índice en disco; con miles de filas
            puede tardar decenas de segundos.
          </p>
        )}

        <div className="dialog-actions">
          <button type="button" className="secondary" disabled={working} onClick={() => dialog.current?.close()}>
            Cancelar
          </button>
          <button type="submit" className="primary" disabled={working || hints.length > 0}>
            {source === "csv" && upload !== null
              ? `Crear e importar ${plural(rowCount, "fila", "filas")}`
              : "Crear tabla"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
