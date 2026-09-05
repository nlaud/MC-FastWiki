import { describe, expect, it } from "vitest";

import { computeLayout, orderedSlots } from "./layout.js";

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

describe("orderedSlots", () => {
  const slotsFor = (n: number): number[] => Array.from({ length: n }, (_, i) => i);

  it("walks a 2x2 grid in reading order rather than round the ring", () => {
    // The bug this function exists for. computeLayout puts slot 2 bottom-right
    // and slot 3 bottom-left, so ascending slot order walked the four windows
    // clockwise: top-left, top-right, bottom-right, bottom-left.
    expect(orderedSlots([0, 1, 2, 3])).toEqual([0, 1, 3, 2]);
  });

  it("agrees with ascending slot order for one, two and three windows", () => {
    // The layout has no cell where the two orders disagree below four windows,
    // so this is a guard against 'fixing' the 2x2 by breaking the small cases.
    expect(orderedSlots([0])).toEqual([0]);
    expect(orderedSlots([0, 1])).toEqual([0, 1]);
    expect(orderedSlots([0, 1, 2])).toEqual([0, 1, 2]);
  });

  it("returns every occupied slot exactly once, for every count 1 through 8", () => {
    for (let n = 1; n <= 8; n++) {
      const occupied = slotsFor(n);
      const ordered = orderedSlots(occupied);
      expect([...ordered].sort((a, b) => a - b)).toEqual(occupied);
    }
  });

  it("never steps up a row, for every count 1 through 8", () => {
    // The whole contract, stated as a property rather than as eight literals:
    // reading order means the row index never decreases, and within one row
    // the column never decreases either.
    for (let n = 1; n <= 8; n++) {
      const occupied = slotsFor(n);
      const layout = computeLayout(occupied);
      const ordered = orderedSlots(occupied);

      for (let i = 1; i < ordered.length; i++) {
        const previous = layout.slots[ordered[i - 1] as number];
        const current = layout.slots[ordered[i] as number];
        if (!previous || !current) throw new Error("missing cell");
        expect(current.row).toBeGreaterThanOrEqual(previous.row);
        if (current.row === previous.row) {
          expect(current.col).toBeGreaterThan(previous.col);
        }
      }
    }
  });

  it("does not care what order the caller passes the slots in", () => {
    expect(orderedSlots([3, 1, 0, 2])).toEqual(orderedSlots([0, 1, 2, 3]));
  });
});
