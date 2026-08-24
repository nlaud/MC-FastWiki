import "./theme/base.css";

// Boot module. It mounts a placeholder. The search bar, the window manager, and
// the renderers arrive in later phases.
function mount(root: HTMLElement): void {
  const placeholder = document.createElement("p");
  placeholder.className = "placeholder";
  placeholder.textContent = "MC-FastWiki — scaffold ready.";
  root.replaceChildren(placeholder);
}

const root = document.querySelector<HTMLElement>("#app");
if (root === null) {
  throw new Error("Mount point #app is missing from index.html");
}
mount(root);
