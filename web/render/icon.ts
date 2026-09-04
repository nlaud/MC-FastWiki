import { loadAtlas } from "../search/load.js";
import type { Atlas, SpriteFrame } from "../types/atlas.js";

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
