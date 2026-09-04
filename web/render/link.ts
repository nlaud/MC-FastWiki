import type { EntityRef, IntegerRange, ItemAmount } from "../types/entity.js";
import type { RenderContext } from "./context.js";
import { createIconElement } from "./icon.js";

/**
 * Type guard to check if the target is an ItemAmount.
 */
export function isItemAmount(target: EntityRef | ItemAmount): target is ItemAmount {
  return "quantity" in target;
}

/**
 * Formats an IntegerRange into a readable string (e.g., "1", "0–2").
 */
export function formatQuantityRange(range: IntegerRange): string {
  if (range.minimum === range.maximum) {
    return range.minimum.toString();
  }
  return `${range.minimum.toString()}–${range.maximum.toString()}`;
}

function formatNote(rawNote: string): { inlineText: string; title?: string } {
  const cleaned = rawNote
    .replace(/<[^>]*>/g, "")
    .replace(/\[\[(?:[^|\]]*\|)?([^\]]+)\]\]/g, "$1")
    .replace(/\s+/g, " ")
    .trim();

  if (cleaned.length > 25) {
    return { inlineText: " (*)", title: cleaned };
  }
  return { inlineText: ` (${cleaned})` };
}

function appendQuantity(host: HTMLElement, quantityStr: string | null): void {
  if (quantityStr === null) {
    return;
  }
  const qtySpan = document.createElement("span");
  qtySpan.className = "item-quantity";
  qtySpan.textContent = `${quantityStr} `;
  host.append(qtySpan);
}

function appendName(host: HTMLElement, name: string): void {
  const nameSpan = document.createElement("span");
  nameSpan.className = "entity-name";
  nameSpan.textContent = name;
  host.append(nameSpan);
}

function appendNote(host: HTMLElement, rawNote: string | undefined): void {
  if (!rawNote) {
    return;
  }
  const noteInfo = formatNote(rawNote);
  const noteSpan = document.createElement("span");
  noteSpan.className = "item-note";
  noteSpan.textContent = noteInfo.inlineText;
  if (noteInfo.title) {
    noteSpan.title = noteInfo.title;
  }
  host.append(noteSpan);
}

/**
 * Turns an EntityRef, or an ItemAmount carrying a ref, into a focusable link with an icon.
 * If the ref is absent, or if the target ID cannot be resolved in the index,
 * prints plain text instead of a dead link.
 */
export function entityLink(target: EntityRef | ItemAmount, ctx: RenderContext): HTMLElement {
  const isItem = isItemAmount(target);
  const ref = isItem ? target.ref : target;
  const displayName = target.name;
  const quantityStr = isItem ? formatQuantityRange(target.quantity) : null;
  const note = isItem ? target.note : undefined;

  // Two cases print plain text rather than a link: the source carried no ref at
  // all, and a ref whose ID the search index does not hold. Both would be a
  // dead click, which is worse than text.
  const entry = ref ? ctx.lookup(ref.id) : null;
  if (!ref || !entry) {
    const plain = document.createElement("span");
    plain.className = "entity-plain";
    appendQuantity(plain, quantityStr);
    appendName(plain, displayName);
    appendNote(plain, note);
    return plain;
  }

  const link = document.createElement("a");
  link.href = "#";
  link.className = "entity-link";
  link.setAttribute("role", "button");
  link.dataset["id"] = ref.id;

  appendQuantity(link, quantityStr);
  link.append(createIconElement(entry.i));
  appendName(link, ref.name || displayName);
  appendNote(link, note);

  link.addEventListener("click", (e) => {
    e.preventDefault();
    ctx.openRef(ref.id);
  });

  link.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      ctx.openRef(ref.id);
    }
  });

  return link;
}
