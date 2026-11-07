import type { PartInfo } from "./api";

/** Which panels a single-part server needs, from its health ``database`` name. */
export function kindOfDatabase(database: string): PartInfo["kind"] {
  if (database === "spatial" || database === "text" || database === "multimedia") return database;
  return "demo";
}

/**
 * The tab named by the address (``#parte3``); otherwise the first ready part,
 * otherwise the first part. Null only when there are no parts at all.
 */
export function partFromHash(hash: string, parts: PartInfo[]): string | null {
  const wanted = hash.replace(/^#/, "");
  if (parts.some((part) => part.id === wanted)) return wanted;
  return (parts.find((part) => part.status === "ready") ?? parts[0])?.id ?? null;
}
