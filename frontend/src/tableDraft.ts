// Editable state of the "Nueva tabla" dialog, kept free of React for testing.
// The server re-validates everything; these checks only give early hints.

import type {
  ColumnType,
  CreateTableRequest,
  CsvPreview,
  IndexType,
  Organization,
} from "./types";

export interface ColumnDraft {
  name: string;
  type: ColumnType;
  /** Original CSV header, when the column comes from an upload. */
  source?: string;
}

export interface IndexDraft {
  column: string;
  type: IndexType;
  unique: boolean;
}

export interface TableDraft {
  name: string;
  organization: Organization;
  keyColumn: string | null;
  columns: ColumnDraft[];
  /** Heap: any B+ / hash indexes. Sequential: only the clustered B+ on the key. */
  indexes: IndexDraft[];
}

export const COLUMN_TYPES: ColumnType[] = ["INTEGER", "FLOAT", "VARCHAR", "BOOLEAN"];

export const INDEX_LABELS: Record<IndexType, string> = {
  BPLUS: "B+",
  EXTENDIBLE_HASH: "Hash extensible",
};

// Same rule as the engine lexer: a letter or _, then letters, digits or _.
const IDENTIFIER = /^[\p{L}_][\p{L}\p{N}_]*$/u;

export function emptyDraft(): TableDraft {
  return {
    name: "",
    organization: "HEAP",
    keyColumn: null,
    columns: [{ name: "id", type: "INTEGER" }],
    indexes: [],
  };
}

export function draftFromPreview(preview: CsvPreview): TableDraft {
  return {
    name: preview.suggested_table_name,
    organization: "HEAP",
    keyColumn: null,
    columns: preview.columns.map((column) => ({ ...column })),
    indexes: [],
  };
}

/**
 * Switch organization keeping the draft coherent with the engine's rules:
 * a Paged Sequential File is ordered by a key and admits only the clustered
 * B+ index on it; Extendible Hashing and unclustered B+ need a Heap File.
 */
export function withOrganization(draft: TableDraft, organization: Organization): TableDraft {
  if (organization === "HEAP") {
    return { ...draft, organization, keyColumn: null, indexes: [] };
  }
  const keyColumn = draft.columns[0]?.name ?? null;
  return { ...draft, organization, keyColumn, indexes: [] };
}

/** Rename a column everywhere it is referenced. */
export function renameColumn(draft: TableDraft, position: number, name: string): TableDraft {
  const previous = draft.columns[position]?.name;
  return {
    ...draft,
    columns: draft.columns.map((column, index) => (index === position ? { ...column, name } : column)),
    keyColumn: draft.keyColumn === previous ? name : draft.keyColumn,
    indexes: draft.indexes.map((index) => (index.column === previous ? { ...index, column: name } : index)),
  };
}

/** Remove a column and every index or key that used it. */
export function removeColumn(draft: TableDraft, position: number): TableDraft {
  const removed = draft.columns[position]?.name;
  const columns = draft.columns.filter((_, index) => index !== position);
  return {
    ...draft,
    columns,
    keyColumn: draft.keyColumn === removed ? (columns[0]?.name ?? null) : draft.keyColumn,
    indexes: draft.indexes.filter((index) => index.column !== removed),
  };
}

export function problems(draft: TableDraft, existingTables: string[]): string[] {
  const found: string[] = [];
  if (draft.name.trim() === "") found.push("Falta el nombre de la tabla.");
  else if (!IDENTIFIER.test(draft.name)) found.push(`«${draft.name}» no es un identificador SQL válido.`);
  else if (existingTables.includes(draft.name)) found.push(`Ya existe una tabla llamada «${draft.name}».`);
  if (draft.columns.length === 0) found.push("La tabla necesita al menos una columna.");
  const seen = new Set<string>();
  for (const column of draft.columns) {
    if (!IDENTIFIER.test(column.name)) found.push(`«${column.name}» no es un nombre de columna válido.`);
    else if (seen.has(column.name)) found.push(`La columna «${column.name}» está repetida.`);
    seen.add(column.name);
  }
  if (draft.organization === "SEQUENTIAL" && (draft.keyColumn === null || !seen.has(draft.keyColumn))) {
    found.push("Elige la columna clave del Paged Sequential File.");
  }
  const pairs = new Set<string>();
  for (const index of draft.indexes) {
    const pair = `${index.column}/${index.type}`;
    if (pairs.has(pair)) found.push(`Hay dos índices ${INDEX_LABELS[index.type]} sobre «${index.column}».`);
    pairs.add(pair);
  }
  return found;
}

export function toRequest(
  draft: TableDraft,
  csv: { text: string; filename: string | null; delimiter: string | null } | null,
): CreateTableRequest {
  const request: CreateTableRequest = {
    name: draft.name,
    organization: draft.organization,
    key_column: draft.organization === "SEQUENTIAL" ? draft.keyColumn : null,
    columns: draft.columns.map(({ name, type }) => ({ name, type })),
    indexes: draft.indexes.map(({ column, type, unique }) => ({ column, type, unique })),
  };
  if (csv !== null) request.csv = csv;
  return request;
}
