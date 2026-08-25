import { beforeEach, describe, expect, it } from "vitest";

import { mount } from "./mount.js";

describe("mount", () => {
  let root: HTMLElement;

  beforeEach(() => {
    document.body.replaceChildren();
    root = document.createElement("div");
    root.id = "app";
    document.body.append(root);
  });

  it("replaces the content of the root element", () => {
    root.append(document.createTextNode("boot text"));

    mount(root);

    expect(root.textContent).toBe("MC-FastWiki — scaffold ready.");
    expect(root.children).toHaveLength(1);
  });

  it("writes a paragraph that the theme can style", () => {
    mount(root);

    const first = root.firstElementChild;
    expect(first?.tagName).toBe("P");
    expect(first?.className).toBe("placeholder");
  });
});
