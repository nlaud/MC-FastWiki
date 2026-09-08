import { loadObtain, loadShard } from "../search/load.js";
import type { Entity, Section } from "../types/entity.js";
import type { IndexEntry } from "../types/index.js";
import type { RenderContext } from "./context.js";
import { buildObtainTree } from "./obtain-tree.js";
import { renderSection } from "./sections/index.js";

/**
 * Renders the full entity content inside a window body:
 * - Loading state while shard is loading
 * - Entity kind badge
 * - Intro blurb (if present)
 * - Rendered sections
 * - Source wiki attribution (if present)
 * - Error state if loading fails
 */
export function renderEntity(container: HTMLElement, entry: IndexEntry, ctx: RenderContext): void {
  container.replaceChildren();

  const loadingEl = document.createElement("div");
  loadingEl.className = "entity-loading";
  loadingEl.textContent = "Loading...";
  container.append(loadingEl);

  void loadShard(entry.s)
    .then((shard) => {
      const rawEntity = shard.entities.find((e) => (e as { id?: string }).id === entry.id);
      if (!rawEntity) {
        throw new Error(`Entity ${entry.id} not found in shard ${entry.s}`);
      }

      const entity = rawEntity as unknown as Entity;
      container.replaceChildren();

      if (entity.blurb) {
        const blurbEl = document.createElement("p");
        blurbEl.className = "entity-blurb";
        blurbEl.textContent = entity.blurb;
        container.append(blurbEl);
      }

      // Render sections
      if (entity.sections.length > 0) {
        const sectionsContainer = document.createElement("div");
        sectionsContainer.className = "entity-sections";
        for (const section of entity.sections) {
          if (
            section.type === "TradeTable" &&
            entity.kind !== "profession" &&
            entity.kind !== "mob"
          ) {
            continue;
          }
          const el = renderSection(section, ctx, entity);
          if (el) {
            sectionsContainer.append(el);
          }
        }
        if (sectionsContainer.hasChildNodes()) {
          container.append(sectionsContainer);
        }
      }

      if (entity.wikiUrl) {
        const attribution = document.createElement("div");
        attribution.className = "entity-attribution";

        const link = document.createElement("a");
        link.href = entity.wikiUrl;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "Minecraft Wiki";

        const note = document.createElement("span");
        note.className = "attribution-license";
        note.textContent = " (CC BY-NC-SA 3.0)";

        attribution.append(link, note);
        container.append(attribution);
      }

      // Synthesise RecipeTree section from obtain graph if this entity has producers
      void loadObtain()
        .then((graph) => {
          const producers = graph.producers[entity.id];
          const hasTrades = entity.sections.some((s) => s.type === "TradeTable");
          if ((!producers || producers.length === 0) && !hasTrades) {
            return;
          }
          const tree = buildObtainTree(entity.id, graph);
          const recipeTreeSection = {
            type: "RecipeTree",
            root: tree.root,
            rawProducers: tree.rawProducers,
            sources: tree.sources,
            graph,
          } as unknown as Section;
          const el = renderSection(recipeTreeSection, ctx, entity);
          if (el) {
            let sectionsEl = container.querySelector<HTMLElement>(".entity-sections");
            if (!sectionsEl) {
              sectionsEl = document.createElement("div");
              sectionsEl.className = "entity-sections";
              const attribution = container.querySelector<HTMLElement>(".entity-attribution");
              if (attribution) {
                container.insertBefore(sectionsEl, attribution);
              } else {
                container.append(sectionsEl);
              }
            }
            sectionsEl.append(el);
          }
        })
        .catch(() => {
          // Failure to load obtain graph does not affect the rest of the entity page
        });
    })
    .catch((err: unknown) => {
      container.replaceChildren();
      const errorEl = document.createElement("div");
      errorEl.className = "entity-error";
      errorEl.textContent = err instanceof Error ? err.message : "Failed to load entity";
      container.append(errorEl);
    });
}
