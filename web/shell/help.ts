import { KEYMAP } from "./keymap.js";

export function createHelpOverlay(onClose: () => void): HTMLElement {
  const backdrop = document.createElement("div");
  backdrop.className = "help-backdrop";
  backdrop.setAttribute("role", "dialog");
  backdrop.setAttribute("aria-modal", "true");
  backdrop.setAttribute("aria-label", "Keyboard Shortcuts");

  const panel = document.createElement("div");
  panel.className = "help-panel";

  const header = document.createElement("div");
  header.className = "help-header";

  const title = document.createElement("h2");
  title.className = "help-title";
  title.textContent = "Keyboard Shortcuts";

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "help-close-btn";
  closeBtn.setAttribute("aria-label", "Close shortcuts overlay");
  closeBtn.textContent = "×";
  closeBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    onClose();
  });

  header.append(title, closeBtn);

  const table = document.createElement("table");
  table.className = "help-table";

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  const thKey = document.createElement("th");
  thKey.textContent = "Key";
  const thDoes = document.createElement("th");
  thDoes.textContent = "Action";
  const thWhen = document.createElement("th");
  thWhen.textContent = "When";
  headerRow.append(thKey, thDoes, thWhen);
  thead.append(headerRow);

  const tbody = document.createElement("tbody");
  for (const entry of KEYMAP) {
    const row = document.createElement("tr");
    row.className = "help-row";

    const tdKey = document.createElement("td");
    tdKey.className = "help-key";
    const kbd = document.createElement("kbd");
    kbd.textContent = entry.key;
    tdKey.append(kbd);

    const tdDoes = document.createElement("td");
    tdDoes.className = "help-does";
    tdDoes.textContent = entry.does;

    const tdWhen = document.createElement("td");
    tdWhen.className = "help-when";
    tdWhen.textContent = entry.when;

    row.append(tdKey, tdDoes, tdWhen);
    tbody.append(row);
  }

  table.append(thead, tbody);
  panel.append(header, table);
  backdrop.append(panel);

  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) {
      onClose();
    }
  });

  return backdrop;
}
