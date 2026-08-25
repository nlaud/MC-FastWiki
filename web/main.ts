import "./theme/base.css";
import { mount } from "./shell/mount.js";

// Boot module. It finds the mount point and hands it to the shell. Keep the
// work here small: everything in this file runs at import time, so nothing
// here can be tested.
const root = document.querySelector<HTMLElement>("#app");
if (root === null) {
  throw new Error("Mount point #app is missing from index.html");
}
mount(root);
