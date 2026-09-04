import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Atlas } from "../types/atlas.js";

// The atlas is fetched, and icon.ts starts that fetch at import time, so the
// stub has to be in place before the module is imported.
const atlas: Atlas = {
  schemaVersion: 1,
  image: "sprites.png",
  width: 512,
  height: 2812,
  sprites: {
    // The three real shapes the committed atlas holds, at their real sizes.
    "EntitySprite:zombie": { x: 432, y: 2492, w: 16, h: 16 },
    "InvSprite:Emerald": { x: 384, y: 2588, w: 32, h: 32 },
    "InvSprite:Sculk": { x: 0, y: 0, w: 300, h: 300 },
    "EntitySprite:marker": { x: 8, y: 8, w: 1, h: 1 },
  },
};

describe("createIconElement", () => {
  let createIconElement: (iconKey?: string) => HTMLElement;

  beforeEach(async () => {
    vi.resetModules();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(atlas) })),
    );
    const iconModule = await import("./icon.js");
    createIconElement = iconModule.createIconElement;
    // Let the atlas load that the module starts on import settle.
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("draws a 16x16 frame at its own size, with the atlas unscaled", async () => {
    const el = createIconElement("EntitySprite:zombie");
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(el.style.width).toBe("16px");
    expect(el.style.height).toBe("16px");
    expect(el.style.backgroundSize).toBe("512px 2812px");
    expect(el.style.backgroundPosition).toBe("-432px -2492px");
  });

  it("halves a 32x32 frame, so item icons match the 16x16 ones beside them", async () => {
    const el = createIconElement("InvSprite:Emerald");
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(el.style.width).toBe("16px");
    expect(el.style.height).toBe("16px");
    // The whole atlas shrinks by the same factor, or the crop lands elsewhere.
    expect(el.style.backgroundSize).toBe("256px 1406px");
    expect(el.style.backgroundPosition).toBe("-192px -1294px");
  });

  it("fits the 300x300 sculk frame into the same box as every other icon", async () => {
    const el = createIconElement("InvSprite:Sculk");
    await new Promise((resolve) => setTimeout(resolve, 0));

    // Drawn at 300px this is taller than the suggestion row that holds it.
    expect(el.style.width).toBe("16px");
    expect(el.style.height).toBe("16px");
  });

  it("never scales a frame up, so a 1x1 sprite is not stretched into invented detail", async () => {
    const el = createIconElement("EntitySprite:marker");
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(el.style.width).toBe("1px");
    expect(el.style.height).toBe("1px");
    expect(el.style.backgroundSize).toBe("512px 2812px");
  });

  it("marks an icon with no key as empty rather than drawing a sprite", () => {
    const el = createIconElement();

    expect(el.classList.contains("is-empty")).toBe(true);
    expect(el.style.backgroundImage).toBe("");
  });
});
