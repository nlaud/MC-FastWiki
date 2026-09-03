import { loadIndex } from "../search/load.js";
import { type Corpus, buildCorpus, search } from "../search/matcher.js";

/**
 * Minimal boot surface for Phase 4.
 * Mounts an input and a ul displaying the top ten matching entities.
 * Phase 5 will replace this with the full shell, window manager, and keyboard map.
 */
export function mount(root: HTMLElement, corpusSource?: Promise<Corpus> | Corpus): void {
  const container = document.createElement("div");
  container.className = "search-container";

  const input = document.createElement("input");
  input.type = "text";
  input.className = "search-input";
  input.placeholder = "Search Minecraft Java...";
  input.autofocus = true;

  const resultsList = document.createElement("ul");
  resultsList.className = "search-results";

  container.append(input, resultsList);
  root.replaceChildren(container);

  const corpusPromise: Promise<Corpus> =
    corpusSource instanceof Promise
      ? corpusSource
      : corpusSource !== undefined
        ? Promise.resolve(corpusSource)
        : loadIndex().then(buildCorpus);

  input.addEventListener("input", () => {
    void corpusPromise.then((corpus) => {
      const results = search(corpus, input.value, 10);
      const items = results.map((entry) => {
        const li = document.createElement("li");
        li.className = "search-result-item";
        li.textContent = entry.n;
        li.dataset["id"] = entry.id;
        li.dataset["kind"] = entry.k;
        return li;
      });
      resultsList.replaceChildren(...items);
    });
  });
}
