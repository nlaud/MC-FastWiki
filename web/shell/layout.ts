export interface GridCell {
  row: number; // 1-based row index
  col: number; // 1-based col index
  rowSpan?: number;
  colSpan?: number;
}

export interface LayoutPlan {
  count: number;
  columns: number;
  rows: number;
  // Maps slot index (0..7) to its cell
  slots: Record<number, GridCell>;
}

/**
 * Computes the grid template and placement for each occupied slot using a binary split layout.
 *
 * | Count | Template | Layout |
 * | 1 | 1x1 | single cell spanning viewport |
 * | 2 | 2x1 | two columns side-by-side |
 * | 3 | 2x2 | left half full height, right half split into 2 rows (no blank cells) |
 * | 4 | 2x2 | 4 quadrants |
 * | 5 | 4x2 | top-left quadrant split into 2 columns, others span 2 cols |
 * | 6 | 4x2 | top-left and top-right split into 2 cols each, bottom two span 2 cols |
 * | 7 | 4x2 | top two and bottom-left split into 2 cols each, bottom-right spans 2 cols |
 * | 8 | 4x2 | all 4 quadrants split into 8 single cells (4 cols x 2 rows) |
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
      slots[s0] = { row: 1, col: 1, rowSpan: 1, colSpan: 1 };
    }
    return { count: 1, columns: 1, rows: 1, slots };
  }

  if (count === 2) {
    const [s0, s1] = sorted;
    if (s0 !== undefined && s1 !== undefined) {
      slots[s0] = { row: 1, col: 1, rowSpan: 1, colSpan: 1 };
      slots[s1] = { row: 1, col: 2, rowSpan: 1, colSpan: 1 };
    }
    return { count: 2, columns: 2, rows: 1, slots };
  }

  if (count === 3) {
    const [s0, s1, s2] = sorted;
    if (s0 !== undefined && s1 !== undefined && s2 !== undefined) {
      slots[s0] = { row: 1, col: 1, rowSpan: 2, colSpan: 1 };
      slots[s1] = { row: 1, col: 2, rowSpan: 1, colSpan: 1 };
      slots[s2] = { row: 2, col: 2, rowSpan: 1, colSpan: 1 };
    }
    return { count: 3, columns: 2, rows: 2, slots };
  }

  if (count === 4) {
    const [s0, s1, s2, s3] = sorted;
    if (s0 !== undefined && s1 !== undefined && s2 !== undefined && s3 !== undefined) {
      slots[s0] = { row: 1, col: 1, rowSpan: 1, colSpan: 1 };
      slots[s1] = { row: 1, col: 2, rowSpan: 1, colSpan: 1 };
      slots[s2] = { row: 2, col: 2, rowSpan: 1, colSpan: 1 };
      slots[s3] = { row: 2, col: 1, rowSpan: 1, colSpan: 1 };
    }
    return { count: 4, columns: 2, rows: 2, slots };
  }

  // 5 to 8 slots: 4 columns x 2 rows
  const [s0, s1, s2, s3, s4, s5, s6, s7] = sorted;
  if (
    s0 === undefined ||
    s1 === undefined ||
    s2 === undefined ||
    s3 === undefined ||
    s4 === undefined
  ) {
    return { count, columns: 4, rows: 2, slots };
  }

  if (count === 5) {
    slots[s0] = { row: 1, col: 1, rowSpan: 1, colSpan: 1 };
    slots[s4] = { row: 1, col: 2, rowSpan: 1, colSpan: 1 };
    slots[s1] = { row: 1, col: 3, rowSpan: 1, colSpan: 2 };
    slots[s2] = { row: 2, col: 3, rowSpan: 1, colSpan: 2 };
    slots[s3] = { row: 2, col: 1, rowSpan: 1, colSpan: 2 };
    return { count: 5, columns: 4, rows: 2, slots };
  }

  if (count === 6 && s5 !== undefined) {
    slots[s0] = { row: 1, col: 1, rowSpan: 1, colSpan: 1 };
    slots[s4] = { row: 1, col: 2, rowSpan: 1, colSpan: 1 };
    slots[s1] = { row: 1, col: 3, rowSpan: 1, colSpan: 1 };
    slots[s5] = { row: 1, col: 4, rowSpan: 1, colSpan: 1 };
    slots[s2] = { row: 2, col: 3, rowSpan: 1, colSpan: 2 };
    slots[s3] = { row: 2, col: 1, rowSpan: 1, colSpan: 2 };
    return { count: 6, columns: 4, rows: 2, slots };
  }

  if (count === 7 && s5 !== undefined && s6 !== undefined) {
    slots[s0] = { row: 1, col: 1, rowSpan: 1, colSpan: 1 };
    slots[s4] = { row: 1, col: 2, rowSpan: 1, colSpan: 1 };
    slots[s1] = { row: 1, col: 3, rowSpan: 1, colSpan: 1 };
    slots[s5] = { row: 1, col: 4, rowSpan: 1, colSpan: 1 };
    slots[s3] = { row: 2, col: 1, rowSpan: 1, colSpan: 1 };
    slots[s6] = { row: 2, col: 2, rowSpan: 1, colSpan: 1 };
    slots[s2] = { row: 2, col: 3, rowSpan: 1, colSpan: 2 };
    return { count: 7, columns: 4, rows: 2, slots };
  }

  if (count >= 8 && s5 !== undefined && s6 !== undefined && s7 !== undefined) {
    slots[s0] = { row: 1, col: 1, rowSpan: 1, colSpan: 1 };
    slots[s4] = { row: 1, col: 2, rowSpan: 1, colSpan: 1 };
    slots[s1] = { row: 1, col: 3, rowSpan: 1, colSpan: 1 };
    slots[s5] = { row: 1, col: 4, rowSpan: 1, colSpan: 1 };
    slots[s3] = { row: 2, col: 1, rowSpan: 1, colSpan: 1 };
    slots[s6] = { row: 2, col: 2, rowSpan: 1, colSpan: 1 };
    slots[s2] = { row: 2, col: 3, rowSpan: 1, colSpan: 1 };
    slots[s7] = { row: 2, col: 4, rowSpan: 1, colSpan: 1 };
    return { count: 8, columns: 4, rows: 2, slots };
  }

  return { count, columns: 4, rows: 2, slots };
}
