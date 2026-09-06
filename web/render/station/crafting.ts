import type { RenderContext } from "../context.js";
import type { TreeInput, TreeProducer } from "../obtain-tree.js";
import { renderSlot } from "./slot.js";

/**
 * Renders a Crafting Table workstation card.
 * - True 3x3 grid positioned according to the shaped recipe pattern.
 * - Shapeless recipes (or missing grid fallback) fill the 3x3 grid left-to-right, one slot per unit of count.
 * - Arrow pointing to result slot.
 * - Result slot with item icon and quantity badge.
 */
export function renderCraftingCard(
  producer: TreeProducer,
  resultItem: string,
  ctx: RenderContext,
): HTMLElement {
  const cardEl = document.createElement("div");
  cardEl.className = "station-card station-crafting";

  const bodyEl = document.createElement("div");
  bodyEl.className = "station-body";

  // Build the 9 cells of the 3x3 grid
  const gridCells: (TreeInput | null)[] = Array<TreeInput | null>(9).fill(null);

  if (
    producer.grid &&
    producer.grid_width !== null &&
    producer.grid_width !== undefined &&
    producer.grid_height !== null &&
    producer.grid_height !== undefined
  ) {
    const gw = producer.grid_width;
    const gh = producer.grid_height;
    for (let r = 0; r < gh && r < 3; r++) {
      for (let c = 0; c < gw && c < 3; c++) {
        const inputIdx = producer.grid[r * gw + c];
        if (inputIdx !== null && inputIdx !== undefined) {
          const input = producer.inputs[inputIdx];
          if (input) {
            gridCells[r * 3 + c] = { ...input, count: 1 };
          }
        }
      }
    }
  } else {
    // Shapeless fallback: fill grid left-to-right, 1 slot per unit of count
    let cellIdx = 0;
    for (const input of producer.inputs) {
      const units = Math.max(1, input.count);
      for (let k = 0; k < units && cellIdx < 9; k++) {
        gridCells[cellIdx++] = { ...input, count: 1 };
      }
    }
  }

  const gridEl = document.createElement("div");
  gridEl.className = "crafting-grid";
  for (const cell of gridCells) {
    gridEl.append(renderSlot(cell, ctx));
  }
  bodyEl.append(gridEl);

  // Arrow
  const arrowEl = document.createElement("div");
  arrowEl.className = "station-arrow";
  arrowEl.textContent = "→";
  bodyEl.append(arrowEl);

  // Result slot
  const resultSlot = renderSlot(resultItem, ctx, {
    count: producer.count,
    isResult: true,
  });
  bodyEl.append(resultSlot);

  cardEl.append(bodyEl);
  return cardEl;
}
