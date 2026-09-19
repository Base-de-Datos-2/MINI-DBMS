import { describe, expect, it } from "vitest";
import {
  completenessMessage,
  formatBytes,
  formatCount,
  formatMs,
  formatValue,
  isNumeric,
  plural,
} from "./format";
import { indexesUsed, splitDetails } from "./plan";
import type { QueryResponse, RuntimeNode } from "./types";

function node(name: string, children: RuntimeNode[] = [], details = {}): RuntimeNode {
  return {
    id: name,
    name,
    output_columns: [],
    details: Object.entries(details).map(([key, value]) => ({ key, value: String(value) })),
    ordered_by: null,
    rows_examined: 0,
    rows_emitted: 0,
    elapsed_ms: 0,
    children,
  };
}

function response(overrides: Partial<QueryResponse>): QueryResponse {
  return {
    request_id: "r",
    mode: "read-only",
    statement: "SELECT",
    kind: "rows",
    columns: [],
    rows: [],
    returned_rows: 0,
    truncated: false,
    truncation_reason: null,
    result_complete: true,
    total_rows: 0,
    affected_rows: null,
    execution_plan: { prepared: { root: node("TableScan"), truncated: false }, runtime: null },
    plan_status: "prepared",
    metrics: { scope: "", partial: false, backend_elapsed_ms: 0, engine: null },
    ...overrides,
  };
}

describe("formatValue", () => {
  it("distinguishes empty strings, zero and false", () => {
    expect(formatValue("", "string")).toEqual({ text: "(cadena vacía)", marker: true });
    expect(formatValue(0, "int64").text).toBe("0");
    expect(formatValue(false, "boolean").text).toBe("FALSE");
  });

  it("shows large integers and non-finite floats verbatim", () => {
    expect(formatValue("9007199254740993", "int64").text).toBe("9007199254740993");
    expect(formatValue("Infinity", "float64").text).toBe("Infinity");
    expect(formatValue(0.1 + 0.2, "float64").text).toBe(String(0.1 + 0.2));
  });

  it("recognizes numeric encodings for alignment", () => {
    expect(isNumeric("int64")).toBe(true);
    expect(isNumeric("string")).toBe(false);
  });
});

describe("completenessMessage", () => {
  const cap = 1024 * 1024;

  it("never presents a preview size as the total", () => {
    const text = completenessMessage(
      response({ returned_rows: 100, truncated: true, truncation_reason: "row_limit",
                 result_complete: false, total_rows: null }),
      cap,
    );
    expect(text).toContain("primeras 100");
    expect(text).toContain("total desconocido");
  });

  it("reports an exact total only when the engine reached the end", () => {
    const text = completenessMessage(
      response({ returned_rows: 40, truncated: true, truncation_reason: "byte_limit",
                 result_complete: true, total_rows: 90 }),
      cap,
    );
    expect(text).toContain("40 de 90");
    expect(text).toContain("1.0 MiB");
  });

  it("treats an empty complete result as a success", () => {
    expect(completenessMessage(response({}), cap)).toContain("vacío");
  });
});

describe("formatting", () => {
  it("uses binary units and switches to seconds above one second", () => {
    expect(formatBytes(196608)).toBe("192 KiB");
    expect(formatBytes(-1)).toBe("—");
    expect(formatMs(12.34)).toBe("12.3 ms");
    expect(formatMs(2500)).toBe("2.50 s");
  });
});

describe("plan details", () => {
  it("surfaces access-path details first but keeps every other one", () => {
    const { headline, rest } = splitDetails([
      { key: "index_name", value: "students_id_hash" },
      { key: "key_column", value: "id" },
    ]);
    expect(headline.map((d) => d.key)).toEqual(["index_name"]);
    expect(rest.map((d) => d.key)).toEqual(["key_column"]);
  });

  it("reads the persisted index name from the key each plan uses", () => {
    const executed = node("Projection", [
      node("IndexScan", [], { index: "UnclusteredHashIndex", index_name: "students_id_hash" }),
    ]);
    const prepared = node("Projection", [node("IndexScan", [], { index: "clientIndex" })]);

    expect(indexesUsed(executed, "runtime")).toEqual(["students_id_hash"]);
    expect(indexesUsed(prepared, "prepared")).toEqual(["clientIndex"]);
  });
});

describe("plural", () => {
  it("agrees in number in Spanish", () => {
    expect(plural(1, "página", "páginas")).toBe("1 página");
    expect(plural(0, "índice", "índices")).toBe("0 índices");
    expect(plural(2, "fila", "filas")).toBe("2 filas");
    // Thousands follow the es-PE locale, as everywhere else in the UI.
    expect(plural(1000, "fila", "filas")).toBe(`${formatCount(1000)} filas`);
  });
});
