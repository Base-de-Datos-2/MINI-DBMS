import { describe, expect, it } from "vitest";
import {
  draftFromPreview,
  emptyDraft,
  problems,
  removeColumn,
  renameColumn,
  toRequest,
  withOrganization,
} from "./tableDraft";
import type { CsvPreview } from "./types";

const preview: CsvPreview = {
  delimiter: ";",
  columns: [
    { source: "Id", name: "id", type: "INTEGER" },
    { source: "Nota", name: "nota", type: "INTEGER" },
  ],
  sample_rows: [["1", "20"]],
  row_count: 1,
  suggested_table_name: "alumnos",
};

describe("table drafts", () => {
  it("start from the server preview", () => {
    const draft = draftFromPreview(preview);
    expect(draft.name).toBe("alumnos");
    expect(draft.columns.map((column) => column.name)).toEqual(["id", "nota"]);
    expect(problems(draft, ["students"])).toEqual([]);
  });

  it("flag names the SQL lexer would reject and existing tables", () => {
    const draft = { ...emptyDraft(), name: "1tabla" };
    expect(problems(draft, [])).toHaveLength(1);
    expect(problems({ ...draft, name: "students" }, ["students"])[0]).toMatch(/Ya existe/);
    expect(problems({ ...draft, name: "año" }, [])).toEqual([]);
  });

  it("keep sequential files to one clustered key", () => {
    const heap = { ...draftFromPreview(preview), indexes: [{ column: "nota", type: "EXTENDIBLE_HASH" as const, unique: false }] };
    const sequential = withOrganization(heap, "SEQUENTIAL");
    expect(sequential.keyColumn).toBe("id");
    expect(sequential.indexes).toEqual([]);
    expect(withOrganization(sequential, "HEAP").keyColumn).toBeNull();
  });

  it("carry renames and removals into keys and indexes", () => {
    let draft = withOrganization(draftFromPreview(preview), "SEQUENTIAL");
    draft = { ...draft, indexes: [{ column: "id", type: "BPLUS", unique: true }] };
    draft = renameColumn(draft, 0, "codigo");
    expect(draft.keyColumn).toBe("codigo");
    expect(draft.indexes[0]?.column).toBe("codigo");
    draft = removeColumn(draft, 0);
    expect(draft.keyColumn).toBe("nota");
    expect(draft.indexes).toEqual([]);
  });

  it("flag duplicate columns and duplicate indexes", () => {
    const draft = {
      ...draftFromPreview(preview),
      columns: [{ name: "id", type: "INTEGER" as const }, { name: "id", type: "VARCHAR" as const }],
      indexes: [
        { column: "id", type: "BPLUS" as const, unique: false },
        { column: "id", type: "BPLUS" as const, unique: true },
      ],
    };
    expect(problems(draft, [])).toHaveLength(2);
  });

  it("build the request the API expects", () => {
    const draft = { ...draftFromPreview(preview), indexes: [{ column: "id", type: "BPLUS" as const, unique: true }] };
    expect(toRequest(draft, null)).toEqual({
      name: "alumnos",
      organization: "HEAP",
      key_column: null,
      columns: [
        { name: "id", type: "INTEGER" },
        { name: "nota", type: "INTEGER" },
      ],
      indexes: [{ column: "id", type: "BPLUS", unique: true }],
    });
    const csv = { text: "Id;Nota\n1;20\n", filename: "a.csv", delimiter: ";" };
    expect(toRequest(draft, csv).csv).toEqual(csv);
  });
});
