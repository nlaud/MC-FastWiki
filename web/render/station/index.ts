import type { RenderContext } from "../context.js";
import type { TreeProducer } from "../obtain-tree.js";
import { renderBrewingCard, renderFillingCard } from "./brewing.js";
import { renderCraftingCard } from "./crafting.js";
import { renderFurnaceCard } from "./furnace.js";
import { renderSmithingCard } from "./smithing.js";
import { renderStonecutterCard } from "./stonecutter.js";

export { advanceTickerForTesting, resetTickerForTesting, subscribeTicker } from "./ticker.js";
export { humaniseTag, renderSlot, type SlotOptions } from "./slot.js";
export { renderCraftingCard } from "./crafting.js";
export { renderFurnaceCard } from "./furnace.js";
export { renderStonecutterCard } from "./stonecutter.js";
export { renderSmithingCard } from "./smithing.js";
export { renderBrewingCard, renderFillingCard } from "./brewing.js";
export { renderLeafCard } from "./leaf.js";

export interface StationCardOptions {
  activeProducerIndex?: number;
  totalProducers?: number;
  onSelectProducer?: (index: number) => void;
}

/**
 * Dispatches to the appropriate workstation card renderer based on method and station,
 * and attaches pagination dots if multiple producers are available.
 */
export function renderStationCard(
  producer: TreeProducer,
  resultItem: string,
  ctx: RenderContext,
  options: StationCardOptions = {},
): HTMLElement {
  let cardEl: HTMLElement;

  if (producer.station === "stonecutter") {
    cardEl = renderStonecutterCard(producer, resultItem, ctx);
  } else if (producer.station === "smithing_table") {
    cardEl = renderSmithingCard(producer, resultItem, ctx);
  } else if (producer.method === "brewing" || producer.station === "brewing_stand") {
    cardEl = renderBrewingCard(producer, resultItem, ctx);
  } else if (producer.method === "filling") {
    cardEl = renderFillingCard(producer, resultItem, ctx);
  } else if (producer.method === "smelting") {
    cardEl = renderFurnaceCard(producer, resultItem, ctx);
  } else {
    // Default to crafting card (covers shaped & shapeless crafting)
    cardEl = renderCraftingCard(producer, resultItem, ctx);
  }

  // Attach pagination controls if there are multiple alternative recipes
  const total = options.totalProducers ?? 1;
  const activeIdx = options.activeProducerIndex ?? 0;

  if (total > 1 && options.onSelectProducer) {
    const onSelect = options.onSelectProducer;
    const paginationEl = document.createElement("div");
    paginationEl.className = "station-pagination";
    paginationEl.setAttribute("role", "tablist");
    paginationEl.setAttribute("aria-label", "Alternative recipes");

    for (let i = 0; i < total; i++) {
      const dot = document.createElement("button");
      dot.className = "station-dot";
      dot.type = "button";
      dot.setAttribute("role", "tab");
      const isSelected = i === activeIdx;
      if (isSelected) {
        dot.classList.add("is-active");
      }
      dot.setAttribute("aria-selected", isSelected ? "true" : "false");
      dot.setAttribute("aria-label", `Recipe ${(i + 1).toString()} of ${total.toString()}`);

      dot.addEventListener("click", (e) => {
        e.stopPropagation();
        onSelect(i);
      });

      paginationEl.append(dot);
    }

    cardEl.append(paginationEl);

    // Clicking the card itself steps to the next recipe.
    //
    // The dots are a small target and they only say *that* there are more; the
    // card is the thing the reader is already looking at. Capture phase, so a
    // slot inside the grid steps the recipe too rather than opening the item it
    // happens to be showing -- on a card with alternatives, "what else can this
    // be made from" is the question the click is asking. Cards with a single
    // recipe keep their slots as links, where there is no such ambiguity.
    cardEl.classList.add("is-steppable");
    cardEl.setAttribute(
      "title",
      `Recipe ${(activeIdx + 1).toString()} of ${total.toString()} -- click for the next`,
    );
    cardEl.addEventListener(
      "click",
      (e) => {
        const target = e.target;
        if (target instanceof Element && target.closest(".station-pagination")) {
          return;
        }
        e.preventDefault();
        e.stopPropagation();
        onSelect((activeIdx + 1) % total);
      },
      true,
    );
  }

  return cardEl;
}
