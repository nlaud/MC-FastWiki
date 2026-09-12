import { describe, expect, it, vi } from "vitest";
import type { CompostInfo } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { renderCompostInfo } from "./compost-info.js";

describe("renderCompostInfo", () => {
  const ctx: RenderContext = {
    openRef: vi.fn(),
    lookup: vi.fn(),
  };

  it("renders composting chance and label", () => {
    const section: CompostInfo = {
      type: "CompostInfo",
      chance: 65,
    };

    const el = renderCompostInfo(section, ctx);
    expect(el).not.toBeNull();
    expect(el?.className).toContain("compost-info-section");
    expect(el?.querySelector(".section-title")?.textContent).toBe("Composting");
    expect(el?.querySelector(".compost-chance-value")?.textContent).toBe("65%");
    expect(el?.querySelector(".compost-chance-label")?.textContent).toBe("chance to add a layer");
  });

  it("renders 100% chance correctly", () => {
    const section: CompostInfo = {
      type: "CompostInfo",
      chance: 100,
    };

    const el = renderCompostInfo(section, ctx);
    expect(el?.querySelector(".compost-chance-value")?.textContent).toBe("100%");
  });
});
