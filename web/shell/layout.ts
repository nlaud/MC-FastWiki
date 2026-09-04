export interface GridCell {
  row: number; // 1-based row index
  col: number; // 1-based col index
}

export interface LayoutPlan {
  count: number;
  columns: number;
  rows: number;
  // Maps slot index (0..3) to its cell { row, col }
  slots: Record<number, GridCell>;
}

/**
 * Computes the grid template and placement for each occupied slot.
 *
 * | Count | Template | Fill order |
 * | 1 | single cell spanning viewport | occupied slot |
 * | 2 | two columns | ascending slot index, left then right |
 * | 3 | 2x2, one cell empty | ascending slot into top-left, top-right, bottom-left |
 * | 4 | 2x2 | ascending slot into top-left, top-right, bottom-left, bottom-right |
 */
export function computeLayout(occupiedSlots: number[]): LayoutPlan {
  const count = occupiedSlots.length;
  const sorted = [...occupiedSlots].sort((a, b) => a - b);
  const slots: Record<number, GridCell> = {};

  if (count === 0) {
    return { count: 0, columns: 1, rows: 1, slots };
  }

  if (count === 1) {
    const s0 = sorted[0];
    if (s0 !== undefined) {
      slots[s0] = { row: 1, col: 1 };
    }
    return { count: 1, columns: 1, rows: 1, slots };
  }

  if (count === 2) {
    const [s0, s1] = sorted;
    if (s0 !== undefined && s1 !== undefined) {
      slots[s0] = { row: 1, col: 1 };
      slots[s1] = { row: 1, col: 2 };
    }
    return { count: 2, columns: 2, rows: 1, slots };
  }

  if (count === 3) {
    const [s0, s1, s2] = sorted;
    if (s0 !== undefined && s1 !== undefined && s2 !== undefined) {
      slots[s0] = { row: 1, col: 1 }; // top-left
      slots[s1] = { row: 1, col: 2 }; // top-right
      slots[s2] = { row: 2, col: 1 }; // bottom-left
    }
    return { count: 3, columns: 2, rows: 2, slots };
  }

  // count === 4
  const [s0, s1, s2, s3] = sorted;
  if (s0 !== undefined && s1 !== undefined && s2 !== undefined && s3 !== undefined) {
    slots[s0] = { row: 1, col: 1 }; // top-left
    slots[s1] = { row: 1, col: 2 }; // top-right
    slots[s2] = { row: 2, col: 1 }; // bottom-left
    slots[s3] = { row: 2, col: 2 }; // bottom-right
  }
  return { count: 4, columns: 2, rows: 2, slots };
}
