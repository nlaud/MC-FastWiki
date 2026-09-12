import { loadObtain, loadShard } from "../search/load.js";
import type { Entity, Section } from "../types/entity.js";
import type { IndexEntry } from "../types/index.js";
import type { RenderContext } from "./context.js";
import { buildObtainTree } from "./obtain-tree.js";
import { renderSection } from "./sections/index.js";

/**
 * Section types that render below the obtain tree rather than above it.
 *
 * Composting chance and furnace burn time are things you do *with* an item you
 * already have, so they read after "how do I get one", not before it. The
 * obtain tree is appended asynchronously once the graph loads, so these cannot
 * simply be ordered in `entity.sections` -- they are held back and appended
 * once that load settles, whether it produced a tree or not.
 *
 * CSS `order` would also move them visually, but it would leave them early in
 * the DOM, so a screen reader and the tab sequence would still meet them before
 * the obtain tree. The ordering is done here so that reading order and visual
 * order stay the same thing.
 */
const TRAILING_SECTION_TYPES = new Set<string>(["CompostInfo", "FuelInfo"]);

/**
 * Returns the `.entity-sections` element, creating it before the attribution
 * block if no section rendered synchronously.
 */
function ensureSectionsContainer(container: HTMLElement): HTMLElement {
  const existing = container.querySelector<HTMLElement>(".entity-sections");
  if (existing) {
    return existing;
  }
  const created = document.createElement("div");
  created.className = "entity-sections";
  const attribution = container.querySelector<HTMLElement>(".entity-attribution");
  if (attribution) {
    container.insertBefore(created, attribution);
  } else {
    container.append(created);
  }
  return created;
}

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
          if (TRAILING_SECTION_TYPES.has(section.type)) {
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
            ensureSectionsContainer(container).append(el);
          }
        })
        .catch(() => {
          // Failure to load obtain graph does not affect the rest of the entity page
        })
        .finally(() => {
          // The trailing sections go last whether or not an obtain tree landed,
          // so this runs on the early return and on the failure path too.
          for (const section of entity.sections) {
            if (!TRAILING_SECTION_TYPES.has(section.type)) {
              continue;
            }
            const el = renderSection(section, ctx, entity);
            if (el) {
              ensureSectionsContainer(container).append(el);
            }
          }
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
