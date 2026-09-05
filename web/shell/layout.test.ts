import { describe, expect, it } from "vitest";

import { computeLayout } from "./layout.js";

describe("layout", () => {
  it("computes empty layout when 0 slots are occupied", () => {
    const layout = computeLayout([]);
    expect(layout.count).toBe(0);
    expect(layout.columns).toBe(1);
    expect(layout.rows).toBe(1);
    expect(Object.keys(layout.slots)).toHaveLength(0);
  });

  it("pins slot assignment across single-slot occupancies", () => {
    for (let slot = 0; slot < 8; slot++) {
      const layout = computeLayout([slot]);
      expect(layout.count).toBe(1);
      expect(layout.columns).toBe(1);
      expect(layout.rows).toBe(1);
      expect(layout.slots[slot]).toEqual({ row: 1, col: 1, rowSpan: 1, colSpan: 1 });
    }
  });

  it("pins slot assignment across 2-slot occupancies as side-by-side columns", () => {
    const layout = computeLayout([0, 1]);
    expect(layout.count).toBe(2);
    expect(layout.columns).toBe(2);
    expect(layout.rows).toBe(1);
    expect(layout.slots[0]).toEqual({ row: 1, col: 1, rowSpan: 1, colSpan: 1 });
    expect(layout.slots[1]).toEqual({ row: 1, col: 2, rowSpan: 1, colSpan: 1 });
  });

  it("splits 3-slot occupancy without blank cells: left half full height, right half split into two", () => {
    const layout = computeLayout([0, 1, 2]);
    expect(layout.count).toBe(3);
    expect(layout.columns).toBe(2);
    expect(layout.rows).toBe(2);
    expect(layout.slots[0]).toEqual({ row: 1, col: 1, rowSpan: 2, colSpan: 1 });
    expect(layout.slots[1]).toEqual({ row: 1, col: 2, rowSpan: 1, colSpan: 1 });
    expect(layout.slots[2]).toEqual({ row: 2, col: 2, rowSpan: 1, colSpan: 1 });
  });

  it("pins 4-slot occupancy into full 2x2 grid", () => {
    const layout = computeLayout([0, 1, 2, 3]);
    expect(layout.count).toBe(4);
    expect(layout.columns).toBe(2);
    expect(layout.rows).toBe(2);
    expect(layout.slots[0]).toEqual({ row: 1, col: 1, rowSpan: 1, colSpan: 1 });
    expect(layout.slots[1]).toEqual({ row: 1, col: 2, rowSpan: 1, colSpan: 1 });
    expect(layout.slots[2]).toEqual({ row: 2, col: 2, rowSpan: 1, colSpan: 1 });
    expect(layout.slots[3]).toEqual({ row: 2, col: 1, rowSpan: 1, colSpan: 1 });
  });

  it("pins 5-slot occupancy into 4x2 grid with top-left split into two columns", () => {
    const layout = computeLayout([0, 1, 2, 3, 4]);
    expect(layout.count).toBe(5);
    expect(layout.columns).toBe(4);
    expect(layout.rows).toBe(2);
    expect(layout.slots[0]).toEqual({ row: 1, col: 1, rowSpan: 1, colSpan: 1 });
    expect(layout.slots[4]).toEqual({ row: 1, col: 2, rowSpan: 1, colSpan: 1 });
    expect(layout.slots[1]).toEqual({ row: 1, col: 3, rowSpan: 1, colSpan: 2 });
    expect(layout.slots[2]).toEqual({ row: 2, col: 3, rowSpan: 1, colSpan: 2 });
    expect(layout.slots[3]).toEqual({ row: 2, col: 1, rowSpan: 1, colSpan: 2 });
  });

  it("pins 8-slot occupancy into 4x2 grid with 8 single cells", () => {
    const layout = computeLayout([0, 1, 2, 3, 4, 5, 6, 7]);
    expect(layout.count).toBe(8);
    expect(layout.columns).toBe(4);
    expect(layout.rows).toBe(2);
    for (let slot = 0; slot < 8; slot++) {
      const cell = layout.slots[slot];
      expect(cell?.colSpan).toBe(1);
      expect(cell?.rowSpan).toBe(1);
    }
  });

  it("guarantees zero blank cells for every count 1 through 8", () => {
    for (let n = 1; n <= 8; n++) {
      const occupied = Array.from({ length: n }, (_, i) => i);
      const layout = computeLayout(occupied);
      let totalArea = 0;
      for (const slot of occupied) {
        const cell = layout.slots[slot];
        if (!cell) throw new Error(`Missing cell for slot ${slot.toString()}`);
        const colSpan = cell.colSpan ?? 1;
        const rowSpan = cell.rowSpan ?? 1;
        totalArea += colSpan * rowSpan;
      }
      expect(totalArea).toBe(layout.columns * layout.rows);
    }
  });

  it("guarantees stability: opening a new window does not move existing slots across the screen", () => {
    const layout2 = computeLayout([0, 1]);
    const layout3 = computeLayout([0, 1, 2]);
    expect(layout3.slots[0]?.col).toBe(layout2.slots[0]?.col);
    expect(layout3.slots[1]?.col).toBe(layout2.slots[1]?.col);

    const layout4 = computeLayout([0, 1, 2, 3]);
    expect(layout4.slots[0]?.col).toBe(layout3.slots[0]?.col);
    expect(layout4.slots[0]?.row).toBe(layout3.slots[0]?.row);
    expect(layout4.slots[1]).toEqual(layout3.slots[1]);
    expect(layout4.slots[2]).toEqual(layout3.slots[2]);
  });
});
