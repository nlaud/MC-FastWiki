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
 * The edge of the box every icon is drawn into, in CSS pixels.
 *
 * The atlas does not hold one sprite size, it holds five. 928 frames are 16x16
 * and 924 are 32x32, so drawing every frame at its own size made half the item
 * icons twice the size of the other half. Three frames are worse: two sculk
 * blocks at 300x300 and a zombie horse spawn egg at 160x160, which the wiki
 * serves as full images rather than as cropped icons. At natural size one of
 * those in a suggestion row is taller than the row.
 */
const DISPLAY_SIZE = 16;

/**
 * Creates an element representing an entity icon.
 * If the atlas is available and has the icon key, renders a cropped pixelated sprite.
 *
 * Every frame is fitted into one `DISPLAY_SIZE` box, keeping its aspect ratio,
 * so an icon is the same size everywhere no matter what the wiki served. A
 * frame is only ever scaled down, never up: the seven 1x1 frames draw things
 * that really are invisible, and stretching one pixel over a whole box would
 * invent detail the sprite does not have.
 */
export function createIconElement(iconKey?: string): HTMLElement {
  const el = document.createElement("span");
  el.className = "entity-icon";

  if (!iconKey) {
    el.classList.add("is-empty");
    return el;
  }

  el.dataset["icon"] = iconKey;

  const applyFrame = (frame: SpriteFrame, atlas: Atlas, imagePath: string): void => {
    // Scaling the frame means scaling the whole atlas behind it by the same
    // factor, because the frame is a window onto one shared image.
    const scale = Math.min(1, DISPLAY_SIZE / Math.max(frame.w, frame.h));
    const px = (value: number): string => `${(value * scale).toString()}px`;

    el.style.width = px(frame.w);
    el.style.height = px(frame.h);
    el.style.backgroundImage = `url("${imagePath}")`;
    el.style.backgroundSize = `${px(atlas.width)} ${px(atlas.height)}`;
    el.style.backgroundPosition = `-${px(frame.x)} -${px(frame.y)}`;
    el.style.backgroundRepeat = "no-repeat";
    el.style.display = "inline-block";
    el.classList.add("has-sprite");
  };

  const base = import.meta.env.BASE_URL.endsWith("/")
    ? import.meta.env.BASE_URL
    : `${import.meta.env.BASE_URL}/`;
  const imagePath = `${base}data/sprites.png`;

  const cachedFrame = cachedAtlas?.sprites[iconKey];
  if (cachedAtlas && cachedFrame) {
    applyFrame(cachedFrame, cachedAtlas, imagePath);
  } else {
    // Attempt to load atlas if not already cached
    void loadAtlas()
      .then((atlas) => {
        cachedAtlas = atlas;
        const frame = atlas.sprites[iconKey];
        if (frame) {
          applyFrame(frame, atlas, imagePath);
        }
      })
      .catch(() => {
        // Silently ignore atlas failure
      });
  }

  return el;
}
