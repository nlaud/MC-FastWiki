import { loadAtlas, loadShard } from "../search/load.js";
import type { Atlas, SpriteFrame } from "../types/atlas.js";
import type { Entity } from "../types/entity.js";
import type { IndexEntry } from "../types/index.js";

let cachedAtlas: Atlas | null = null;

// Kick off background atlas load
void loadAtlas()
  .then((atlas) => {
    cachedAtlas = atlas;
  })
  .catch(() => {
    // Atlas load failure should not crash the app
  });

/**
 * Creates an element representing an entity icon.
 * If the atlas is available and has the icon key, renders a cropped pixelated sprite.
 */
export function createIconElement(iconKey?: string): HTMLElement {
  const el = document.createElement("span");
  el.className = "entity-icon";

  if (!iconKey) {
    el.classList.add("is-empty");
    return el;
  }

  el.dataset["icon"] = iconKey;

  const applyFrame = (frame: SpriteFrame, imagePath: string): void => {
    el.style.width = `${frame.w.toString()}px`;
    el.style.height = `${frame.h.toString()}px`;
    el.style.backgroundImage = `url("${imagePath}")`;
    el.style.backgroundPosition = `-${frame.x.toString()}px -${frame.y.toString()}px`;
    el.style.backgroundRepeat = "no-repeat";
    el.style.display = "inline-block";
    el.classList.add("has-sprite");
  };

  const base = import.meta.env.BASE_URL.endsWith("/")
    ? import.meta.env.BASE_URL
    : `${import.meta.env.BASE_URL}/`;
  const imagePath = `${base}data/sprites.png`;

  if (cachedAtlas && cachedAtlas.sprites[iconKey]) {
    applyFrame(cachedAtlas.sprites[iconKey], imagePath);
  } else {
    // Attempt to load atlas if not already cached
    void loadAtlas()
      .then((atlas) => {
        cachedAtlas = atlas;
        const frame = atlas.sprites[iconKey];
        if (frame) {
          applyFrame(frame, imagePath);
        }
      })
      .catch(() => {
        // Silently ignore atlas failure
      });
  }

  return el;
}

/**
 * Fallback renderer for entity window content.
 * Displays loading state synchronously, fetches the shard, and renders:
 * - kind badge
 * - intro blurb (if present)
 * - wiki attribution link (if present)
 */
export function renderFallback(container: HTMLElement, entry: IndexEntry): void {
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

      const meta = document.createElement("div");
      meta.className = "entity-meta";

      const badge = document.createElement("span");
      badge.className = "entity-kind-badge";
      badge.textContent = entity.kind;
      meta.append(badge);

      container.append(meta);

      if (entity.blurb) {
        const blurbEl = document.createElement("p");
        blurbEl.className = "entity-blurb";
        blurbEl.textContent = entity.blurb;
        container.append(blurbEl);
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
    })
    .catch((err: unknown) => {
      container.replaceChildren();
      const errorEl = document.createElement("div");
      errorEl.className = "entity-error";
      errorEl.textContent = err instanceof Error ? err.message : "Failed to load entity";
      container.append(errorEl);
    });
}
