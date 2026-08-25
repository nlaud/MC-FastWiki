// Placeholder content of the app shell. The search bar, the window manager,
// and the renderers arrive in later phases.
//
// This function holds no import with a side effect, so a test can call it
// without booting the page.
export function mount(root: HTMLElement): void {
  const placeholder = document.createElement("p");
  placeholder.className = "placeholder";
  placeholder.textContent = "MC-FastWiki — scaffold ready.";
  root.replaceChildren(placeholder);
}
