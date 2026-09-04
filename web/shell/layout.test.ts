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
    for (let slot = 0; slot < 4; slot++) {
      const layout = computeLayout([slot]);
      expect(layout.count).toBe(1);
      expect(layout.columns).toBe(1);
      expect(layout.rows).toBe(1);
      expect(layout.slots[slot]).toEqual({ row: 1, col: 1 });
    }
  });

  it("pins slot assignment across all 2-slot occupancies as side-by-side columns", () => {
    // All 6 pairs: (0,1), (0,2), (0,3), (1,2), (1,3), (2,3)
    const pairs: [number, number][] = [
      [0, 1],
      [0, 2],
      [0, 3],
      [1, 2],
      [1, 3],
      [2, 3],
    ];

    for (const [first, second] of pairs) {
      const layout = computeLayout([first, second]);
      expect(layout.count).toBe(2);
      expect(layout.columns).toBe(2);
      expect(layout.rows).toBe(1);
      expect(layout.slots[first]).toEqual({ row: 1, col: 1 });
      expect(layout.slots[second]).toEqual({ row: 1, col: 2 });
    }
  });

  it("pins slot assignment across all 3-slot occupancies into 2x2 with empty cell", () => {
    // All 4 triplets: (0,1,2), (0,1,3), (0,2,3), (1,2,3)
    const triplets: [number, number, number][] = [
      [0, 1, 2],
      [0, 1, 3],
      [0, 2, 3],
      [1, 2, 3],
    ];

    for (const [s0, s1, s2] of triplets) {
      const layout = computeLayout([s0, s1, s2]);
      expect(layout.count).toBe(3);
      expect(layout.columns).toBe(2);
      expect(layout.rows).toBe(2);
      expect(layout.slots[s0]).toEqual({ row: 1, col: 1 }); // top-left
      expect(layout.slots[s1]).toEqual({ row: 1, col: 2 }); // top-right
      expect(layout.slots[s2]).toEqual({ row: 2, col: 1 }); // bottom-left
      // bottom-right { row: 2, col: 2 } is empty
      expect(Object.values(layout.slots)).not.toContainEqual({ row: 2, col: 2 });
    }
  });

  it("pins 4-slot occupancy into full 2x2 grid", () => {
    const layout = computeLayout([0, 1, 2, 3]);
    expect(layout.count).toBe(4);
    expect(layout.columns).toBe(2);
    expect(layout.rows).toBe(2);
    expect(layout.slots[0]).toEqual({ row: 1, col: 1 });
    expect(layout.slots[1]).toEqual({ row: 1, col: 2 });
    expect(layout.slots[2]).toEqual({ row: 2, col: 1 });
    expect(layout.slots[3]).toEqual({ row: 2, col: 2 });
  });

  it("guarantees growth stability: opening the fourth window does not move slots 0 through 2", () => {
    const layout3 = computeLayout([0, 1, 2]);
    const layout4 = computeLayout([0, 1, 2, 3]);

    expect(layout4.slots[0]).toEqual(layout3.slots[0]);
    expect(layout4.slots[1]).toEqual(layout3.slots[1]);
    expect(layout4.slots[2]).toEqual(layout3.slots[2]);
    expect(layout4.slots[3]).toEqual({ row: 2, col: 2 });
  });

  it("pins the D1 canonical reflow table on close", () => {
    // Close from 4 windows: closing slot 1 leaves 0, 2, 3 reflowed into top-left, top-right, bottom-left
    const reflowFrom4 = computeLayout([0, 2, 3]);
    expect(reflowFrom4.slots[0]).toEqual({ row: 1, col: 1 });
    expect(reflowFrom4.slots[2]).toEqual({ row: 1, col: 2 });
    expect(reflowFrom4.slots[3]).toEqual({ row: 2, col: 1 });

    // Close from 3 windows: closing slot 2 leaves 0 and 3 side by side (left and right)
    const reflowFrom3 = computeLayout([0, 3]);
    expect(reflowFrom3.columns).toBe(2);
    expect(reflowFrom3.rows).toBe(1);
    expect(reflowFrom3.slots[0]).toEqual({ row: 1, col: 1 });
    expect(reflowFrom3.slots[3]).toEqual({ row: 1, col: 2 });

    // Close to 1 window: closing slot 0 leaves slot 3 full-screen
    const reflowFrom2 = computeLayout([3]);
    expect(reflowFrom2.columns).toBe(1);
    expect(reflowFrom2.rows).toBe(1);
    expect(reflowFrom2.slots[3]).toEqual({ row: 1, col: 1 });
  });
});
