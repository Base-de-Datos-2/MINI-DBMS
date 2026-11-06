import { describe, expect, it } from "vitest";
import { mediaContext, mediaUrl, scoreNote, type MultimediaTable } from "./multimedia";
import type { QueryResponse } from "./types";

const tables: MultimediaTable[] = [{
  table: "imagenes", modality: "image", key_column: "media_key", id_column: "id", objects: 8,
  dimension: 16, methods: { HNSW: ["cosine"], IVF: ["cosine"] }, queries: ["foto_consulta.jpg"],
  collection_id: "c1",
}];

function body(name: string, table = "imagenes"): QueryResponse {
  return {
    execution_plan: {
      prepared: {
        root: {
          name, output_columns: [], ordered_by: null, children: [],
          details: [{ key: "table", value: table }, { key: "metric", value: "cosine" },
            { key: "method", value: "HNSW" }, { key: "media_key", value: "foto_consulta.jpg" }],
        },
        truncated: false,
      },
      runtime: null,
    },
  } as unknown as QueryResponse;
}

describe("multimedia results", () => {
  it("recognizes vector scans over published collections", () => {
    expect(mediaContext(body("VectorIndexScan"), tables)).toEqual({
      table: "imagenes", modality: "image", keyColumn: "media_key", queryKey: "foto_consulta.jpg",
      metric: "cosine", method: "HNSW",
    });
    expect(mediaContext(body("VectorScan"), tables)?.modality).toBe("image");
  });

  it("ignores relational plans and unknown tables", () => {
    expect(mediaContext(body("TableScan"), tables)).toBeNull();
    expect(mediaContext(body("VectorIndexScan", "otra"), tables)).toBeNull();
    expect(mediaContext({ execution_plan: null } as unknown as QueryResponse, tables)).toBeNull();
  });

  it("encodes keys and explains scores", () => {
    expect(mediaUrl("imagenes", "a b.jpg")).toBe("/api/multimedia/imagenes/media/a%20b.jpg");
    expect(mediaUrl("imagenes", "../x.jpg")).toBe("/api/multimedia/imagenes/media/..%2Fx.jpg");
    expect(scoreNote("euclidean")).toContain("−distancia");
    expect(scoreNote(null)).toBeNull();
  });
});
