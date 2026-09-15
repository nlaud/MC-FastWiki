import { describe, expect, it } from "vitest";

import { extractAssetHrefs } from "./scripts/smoke-test.js";

describe("smoke-test HTML parser", () => {
  it("extracts script src and link href attributes", () => {
    const sampleHtml = `
      <!doctype html>
      <html>
        <head>
          <link rel="stylesheet" crossorigin href="./assets/index-DMecyHRf.css">
          <link rel="icon" type="image/png" href="./favicon.png">
          <script type="module" crossorigin src="./assets/index-CKy8C0tI.js"></script>
        </head>
        <body>
          <div id="app"></div>
        </body>
      </html>
    `;

    const hrefs = extractAssetHrefs(sampleHtml);
    expect(hrefs).toContain("./assets/index-DMecyHRf.css");
    expect(hrefs).toContain("./favicon.png");
    expect(hrefs).toContain("./assets/index-CKy8C0tI.js");
  });

  it("handles html with no matching assets", () => {
    const emptyHtml = "<html><body><div>hello</div></body></html>";
    const hrefs = extractAssetHrefs(emptyHtml);
    expect(hrefs).toEqual([]);
  });
});
