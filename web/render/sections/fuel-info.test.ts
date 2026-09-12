import { describe, expect, it, vi } from "vitest";
import type { FuelInfo } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { renderFuelInfo } from "./fuel-info.js";

describe("renderFuelInfo", () => {
  const ctx: RenderContext = {
    openRef: vi.fn(),
    lookup: vi.fn(),
  };

  it("renders integer duration and plural items smelted", () => {
    const section: FuelInfo = {
      type: "FuelInfo",
      burnTime: 1600,
    };

    const el = renderFuelInfo(section, ctx);
    expect(el).not.toBeNull();
    expect(el?.className).toContain("fuel-info-section");
    expect(el?.querySelector(".section-title")?.textContent).toBe("Furnace Fuel");
    expect(el?.querySelector(".fuel-burn-duration")?.textContent).toBe("80s");
    expect(el?.querySelector(".fuel-burn-label")?.textContent).toBe("burn time (1,600 ticks)");
    expect(el?.querySelector(".fuel-smelt-count")?.textContent).toBe("8");
    expect(el?.querySelector(".fuel-smelt-label")?.textContent).toBe("items smelted");
  });

  it("renders singular item smelted for 200 ticks (1 item)", () => {
    const section: FuelInfo = {
      type: "FuelInfo",
      burnTime: 200,
    };

    const el = renderFuelInfo(section, ctx);
    expect(el?.querySelector(".fuel-burn-duration")?.textContent).toBe("10s");
    expect(el?.querySelector(".fuel-smelt-count")?.textContent).toBe("1");
    expect(el?.querySelector(".fuel-smelt-label")?.textContent).toBe("item smelted");
  });

  it("renders fractional burn duration and fractional operations", () => {
    const section: FuelInfo = {
      type: "FuelInfo",
      burnTime: 50,
    };

    const el = renderFuelInfo(section, ctx);
    expect(el?.querySelector(".fuel-burn-duration")?.textContent).toBe("2.5s");
    expect(el?.querySelector(".fuel-smelt-count")?.textContent).toBe("0.25");
    expect(el?.querySelector(".fuel-smelt-label")?.textContent).toBe("items smelted");
  });

  it("renders scaffolding burn duration (67 ticks)", () => {
    const section: FuelInfo = {
      type: "FuelInfo",
      burnTime: 67,
    };

    const el = renderFuelInfo(section, ctx);
    expect(el?.querySelector(".fuel-burn-duration")?.textContent).toBe("3.35s");
    expect(el?.querySelector(".fuel-smelt-count")?.textContent).toBe("0.34");
  });
});
