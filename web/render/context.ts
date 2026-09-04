import type { IndexEntry } from "../types/index.js";

/**
 * Context provided to entity renderers for resolving entity references
 * and opening entities in the window manager.
 */
export interface RenderContext {
  /**
   * Opens an entity by ID in the next free window slot.
   */
  openRef: (id: string) => void;

  /**
   * Looks up an entity in the loaded search index.
   * If absent from the index, resolves to null, and the renderer prints plain text
   * instead of a dead link.
   */
  lookup: (id: string) => IndexEntry | null;
}
