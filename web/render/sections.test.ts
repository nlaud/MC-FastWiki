import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type {
  AdvancementInfo,
  DropTable,
  Entity,
  SpawnInfo,
  StatBlock,
  TradeTable,
} from "../types/entity.js";
import type { Index, IndexEntry } from "../types/index.js";
import type { RenderContext } from "./context.js";
import { renderAdvancementInfo } from "./sections/advancement-info.js";
import { renderDropTable } from "./sections/drop-table.js";
import { renderSpawnInfo } from "./sections/spawn-info.js";
import { renderStatBlock } from "./sections/stat-block.js";
import { renderTradeTable } from "./sections/trade-table.js";

function requireItem<T>(item: T | undefined | null, name: string): T {
  if (item === undefined || item === null) {
    throw new Error(`Expected ${name} to be defined`);
  }
  return item;
}

describe("Section renderers with real committed build data", () => {
  let zombie: Entity;
  let apple: Entity;
  let emerald: Entity;
  let sneak100: Entity;
  let ctx: RenderContext;

  beforeAll(() => {
    // Load real dist data
    const mob0Raw = fs.readFileSync(
      path.resolve(process.cwd(), "data/dist/entities/mob-0.json"),
      "utf8",
    );
    const mob0 = JSON.parse(mob0Raw) as { entities: Entity[] };
    zombie = requireItem(
      mob0.entities.find((e) => e.id === "minecraft:zombie"),
      "Zombie",
    );

    const item0Raw = fs.readFileSync(
      path.resolve(process.cwd(), "data/dist/entities/item-0.json"),
      "utf8",
    );
    const item0 = JSON.parse(item0Raw) as { entities: Entity[] };
    apple = requireItem(
      item0.entities.find((e) => e.id === "minecraft:apple"),
      "Apple",
    );
    emerald = requireItem(
      item0.entities.find((e) => e.id === "minecraft:emerald"),
      "Emerald",
    );

    const adv0Raw = fs.readFileSync(
      path.resolve(process.cwd(), "data/dist/entities/advancement-0.json"),
      "utf8",
    );
    const adv0 = JSON.parse(adv0Raw) as { entities: Entity[] };
    sneak100 = requireItem(
      adv0.entities.find((e) => e.id === "minecraft:adventure/avoid_vibration"),
      "Sneak 100",
    );

    const indexRaw = fs.readFileSync(path.resolve(process.cwd(), "data/dist/index.json"), "utf8");
    const index = JSON.parse(indexRaw) as Index;

    const idMap = new Map<string, IndexEntry>();
    const nameMap = new Map<string, IndexEntry>();

    for (const entry of index.entities) {
      idMap.set(entry.id, entry);
      if (!nameMap.has(entry.n.toLowerCase())) {
        nameMap.set(entry.n.toLowerCase(), entry);
      }
    }

    ctx = {
      openRef: vi.fn(),
      lookup: (id: string) => {
        return (
          idMap.get(id) ??
          nameMap.get(id.toLowerCase()) ??
          idMap.get(`minecraft:${id.toLowerCase().replace(/\s+/g, "_")}`) ??
          null
        );
      },
    };
  });

  describe("StatBlock (Zombie)", () => {
    it("renders HP, damage, armor, behavior, size and excludes speed/knockback", () => {
      const statSection = requireItem(
        zombie.sections.find((s): s is StatBlock => s.type === "StatBlock"),
        "StatBlock",
      );

      const el = requireItem(renderStatBlock(statSection, ctx), "StatBlock element");
      const text = el.textContent;

      // Health base and variant
      expect(text).toContain("20 HP");
      expect(text).toContain("40–100 HP (leaders)");

      // Armor
      expect(text).toContain("2 Armor");

      // Behavior and Mob type
      const behaviorBadge = el.querySelector(".stat-behavior");
      expect(behaviorBadge?.textContent).toBe("Hostile");
      expect(behaviorBadge?.classList.contains("is-hostile")).toBe(true);

      const mobTypeBadges = Array.from(el.querySelectorAll(".stat-mob-type")).map(
        (b) => b.textContent,
      );
      expect(mobTypeBadges).toContain("Undead");
      expect(mobTypeBadges).toContain("Monster");

      // Damage per difficulty
      expect(text).toContain("Easy: 2.5 dmg");
      expect(text).toContain("Normal: 3 dmg");
      expect(text).toContain("Hard: 4.5 dmg");

      // Size
      expect(text).toContain("0.6 × 1.95m (Adult)");
      expect(text).toContain("0.49 × 0.98m (Baby)");

      // INVARIANT: speed and knockbackResistance MUST NOT be rendered
      expect(text).not.toContain("0.23");
      expect(text).not.toContain("0.35");
      expect(text).not.toContain("0%–5%");
      expect(text.toLowerCase()).not.toContain("speed");
      expect(text.toLowerCase()).not.toContain("knockback");
    });
  });

  describe("DropTable (Zombie)", () => {
    it("renders table with 4 looting columns and collapses past 6 rows", () => {
      const dropSection = requireItem(
        zombie.sections.find((s): s is DropTable => s.type === "DropTable"),
        "DropTable",
      );
      const drops = requireItem(dropSection.drops, "drops");
      expect(drops.length).toBeGreaterThan(6);

      const el = requireItem(renderDropTable(dropSection, ctx), "DropTable element");

      // Headers
      const ths = Array.from(el.querySelectorAll("th")).map((th) => th.textContent);
      expect(ths).toEqual(["Item", "Looting 0", "Looting I", "Looting II", "Looting III"]);

      // Rows count
      const rows = el.querySelectorAll("tbody tr");
      expect(rows).toHaveLength(drops.length);

      // Collapsed past 6
      const collapsedInitial = el.querySelectorAll("tbody tr.is-collapsed-row");
      expect(collapsedInitial).toHaveLength(drops.length - 6);

      // Toggle button
      const toggleBtn = requireItem(
        el.querySelector<HTMLButtonElement>(".show-more-btn"),
        "toggle button",
      );
      expect(toggleBtn.textContent).toBe(`Show all ${drops.length.toString()}`);

      // Click expands
      toggleBtn.click();
      expect(el.querySelectorAll("tbody tr.is-collapsed-row")).toHaveLength(0);
      expect(toggleBtn.textContent).toBe("Show less");

      // Guaranteed drop shows quantityText (Zombie Head has 1/1 drop chance)
      const zombieHeadRow = requireItem(
        Array.from(rows).find((r) => r.textContent.includes("Zombie Head")),
        "Zombie Head row",
      );
      const headCells = zombieHeadRow.querySelectorAll(".looting-cell");
      expect(headCells[0]?.textContent).toBe("1");

      // A drop that can yield more than one shows the quantity, because the
      // question there is how many (Rotten Flesh is 0-2 at looting 0)
      const rottenFleshRow = requireItem(
        Array.from(rows).find((r) => r.textContent.includes("Rotten Flesh")),
        "Rotten Flesh row",
      );
      const rottenCells = rottenFleshRow.querySelectorAll(".looting-cell");
      expect(rottenCells[0]?.textContent).toBe("0–2");
      expect(rottenCells[0]?.getAttribute("title")).toContain("66.7% chance");

      // A drop capped at one shows the chance, because the question there is
      // whether it drops at all (Iron Ingot is 1/120 at looting 0)
      const ironRow = requireItem(
        Array.from(rows).find((r) => r.textContent.includes("Iron Ingot")),
        "Iron Ingot row",
      );
      const ironCells = ironRow.querySelectorAll(".looting-cell");
      expect(ironCells[0]?.textContent).toBe("0.8%");
    });
  });

  describe("SpawnInfo (Zombie)", () => {
    it("renders as plain inline list of linked biomes sorted by share descending", () => {
      const spawnSection = requireItem(
        zombie.sections.find((s): s is SpawnInfo => s.type === "SpawnInfo"),
        "SpawnInfo",
      );
      const entries = requireItem(spawnSection.entries, "entries");

      const el = requireItem(renderSpawnInfo(spawnSection, ctx), "SpawnInfo element");

      // NOT a table
      expect(el.querySelector("table")).toBeNull();

      const items = el.querySelectorAll(".spawn-biome-item");
      expect(items.length).toBe(entries.length);

      // Verify sorting: first item has high share
      const firstEntryBiome = entries.reduce((prev, curr) => {
        const prevShare = prev.weight / prev.totalWeight;
        const currShare = curr.weight / curr.totalWeight;
        return currShare > prevShare ? curr : prev;
      });
      expect(items[0]?.textContent).toContain(firstEntryBiome.biome);

      // Check collapsing at 12 items
      const collapsedInitial = el.querySelectorAll(".is-collapsed-item");
      expect(collapsedInitial.length).toBe(entries.length - 12);

      const toggleBtn = requireItem(
        el.querySelector<HTMLButtonElement>(".show-more-btn"),
        "toggle button",
      );
      expect(toggleBtn.textContent).toBe(`Show all ${entries.length.toString()}`);

      toggleBtn.click();
      expect(el.querySelectorAll(".is-collapsed-item")).toHaveLength(0);
    });
  });

  describe("TradeTable (Apple & Emerald)", () => {
    it("renders Apple trade grouped by profession and level with links", () => {
      const tradeSection = requireItem(
        apple.sections.find((s): s is TradeTable => s.type === "TradeTable"),
        "TradeTable",
      );

      const el = requireItem(renderTradeTable(tradeSection, ctx), "TradeTable element");

      expect(el.querySelector(".trade-profession-title")?.textContent).toBe("Farmer");
      expect(el.querySelector(".trade-level-cell")?.textContent).toBe("Apprentice");

      // Wanted link
      const wantedLink = requireItem(
        el.querySelector(".trade-wanted-cell .entity-link"),
        "wanted link",
      );
      expect(wantedLink.textContent).toContain("Emerald");

      // Given link
      const givenLink = requireItem(
        el.querySelector(".trade-given-cell .entity-link"),
        "given link",
      );
      expect(givenLink.textContent).toContain("Apple");

      // No collapse button for 1 trade
      expect(el.querySelector(".show-more-btn")).toBeNull();
    });

    it("renders Emerald with 87 trades, collapsing past 6 with Show all button", () => {
      const tradeSection = requireItem(
        emerald.sections.find((s): s is TradeTable => s.type === "TradeTable"),
        "TradeTable",
      );
      const trades = requireItem(tradeSection.trades, "trades");
      expect(trades.length).toBe(87);

      const el = requireItem(renderTradeTable(tradeSection, ctx), "TradeTable element");

      // Collapsed rows exist
      const collapsedRows = el.querySelectorAll(".is-collapsed-row");
      expect(collapsedRows.length).toBe(87 - 6);

      const toggleBtn = requireItem(
        el.querySelector<HTMLButtonElement>(".show-more-btn"),
        "toggle button",
      );
      expect(toggleBtn.textContent).toBe("Show all 87 trades");

      toggleBtn.click();
      expect(el.querySelectorAll(".is-collapsed-row")).toHaveLength(0);
      expect(toggleBtn.textContent).toBe("Show less");
    });
  });

  describe("AdvancementInfo (Sneak 100)", () => {
    it("renders title, parent link, and parsed gameDescription with entity links", () => {
      const advSection = requireItem(
        sneak100.sections.find((s): s is AdvancementInfo => s.type === "AdvancementInfo"),
        "AdvancementInfo",
      );

      const el = requireItem(renderAdvancementInfo(advSection, ctx), "AdvancementInfo element");

      // The title is not rendered: it equals the entity name for every
      // advancement in the build, and the window header already shows it
      expect(el.querySelector(".advancement-title")).toBeNull();

      // Parent link
      const parentLink = requireItem(
        el.querySelector(".advancement-parent .entity-link"),
        "parent link",
      );
      expect(parentLink.textContent).toContain("Adventure");

      // Description is from gameDescription, not wikitext description
      const desc = requireItem(el.querySelector(".advancement-description"), "description element");
      expect(desc.textContent).toBe(
        "Sneak near a Sculk Sensor or Warden to prevent it from detecting you",
      );

      // Decision 1: Do not render wikitext description
      expect(el.textContent).not.toContain("Sneak while causing a vibration");
    });
  });
});
