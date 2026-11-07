import { createContext, useContext } from "react";
import { rootApi, type Api } from "./api";

/**
 * What one tab (one project part) shares with its panels: the API client bound
 * to that part's prefix, and a function that makes element ids unique, because
 * every tab stays mounted and several tabs contain the same panels.
 */
export interface WorkspaceScope {
  api: Api;
  id: (name: string) => string;
}

/** A single-part server: root API and the plain ids the browser checks use. */
export const ROOT_SCOPE: WorkspaceScope = { api: rootApi, id: (name) => name };

export const WorkspaceContext = createContext<WorkspaceScope>(ROOT_SCOPE);

export const useWorkspace = (): WorkspaceScope => useContext(WorkspaceContext);

export function scopeFor(api: Api, partId: string | null): WorkspaceScope {
  return { api, id: partId === null ? (name) => name : (name) => `${partId}-${name}` };
}
