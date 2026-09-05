import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type {
  AdvancementInfo,
  BreedingInfo,
  DropTable,
  Entity,
  SpawnInfo,
  StatBlock,
  TradeTable,
} from "../types/entity.js";
import type { Index, IndexEntry } from "../types/index.js";
import type { RenderContext } from "./context.js";
import { renderAdvancementInfo } from "./sections/advancement-info.js";
import { renderBreedingInfo } from "./sections/breeding-info.js";
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

      // Damage formatted across difficulties
      expect(text).toContain("2.5/3/4.5 dmg");
      expect(text).not.toContain("Easy: 2.5 dmg");

      // Visual icons for hearts, armor, damage, size
      // 20 HP fills a player bar, and the 40-100 HP leader row fills one too
      // and marks the overflow with a single "+".
      expect(el.querySelectorAll(".icon-heart-full")).toHaveLength(20);
      expect(el.querySelectorAll(".stat-icons-more")).toHaveLength(1);
      expect(el.querySelectorAll(".icon-armor-full")).toHaveLength(1);
      expect(el.querySelectorAll(".icon-damage")).toHaveLength(1);
      expect(el.querySelectorAll(".icon-size")).toHaveLength(2);

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

    it("caps the heart row at a full player bar instead of drawing one lone heart", () => {
      const warden: StatBlock = {
        type: "StatBlock",
        health: [{ value: { minimum: 500, maximum: 500 }, labels: [] }],
        armor: [],
        damage: [],
        size: [],
        behavior: [],
        mobType: [],
        speed: [],
        knockbackResistance: [],
      };

      const el = requireItem(renderStatBlock(warden, ctx), "Warden StatBlock element");

      expect(el.querySelectorAll(".icon-heart-full")).toHaveLength(10);
      expect(el.querySelectorAll(".icon-heart-half")).toHaveLength(0);
      expect(el.querySelector(".stat-icons-more")?.textContent).toBe("+");
      expect(el.textContent).toContain("500 HP");
    });

    it("draws an exact sub-bar health value without an overflow marker", () => {
      const chicken: StatBlock = {
        type: "StatBlock",
        health: [{ value: { minimum: 4, maximum: 4 }, labels: [] }],
        armor: [],
        damage: [],
        size: [],
        behavior: [],
        mobType: [],
        speed: [],
        knockbackResistance: [],
      };

      const el = requireItem(renderStatBlock(chicken, ctx), "Chicken StatBlock element");

      expect(el.querySelectorAll(".icon-heart-full")).toHaveLength(2);
      expect(el.querySelectorAll(".stat-icons-more")).toHaveLength(0);
    });

    it("marks an armour range that starts at zero rather than drawing one icon", () => {
      const player: StatBlock = {
        type: "StatBlock",
        health: [],
        armor: [{ value: { minimum: 0, maximum: 20 }, labels: [] }],
        damage: [],
        size: [],
        behavior: [],
        mobType: [],
        speed: [],
        knockbackResistance: [],
      };

      const el = requireItem(renderStatBlock(player, ctx), "Player StatBlock element");

      expect(el.querySelectorAll(".icon-armor-full")).toHaveLength(0);
      expect(el.querySelectorAll(".icon-armor-half")).toHaveLength(0);
      expect(el.querySelector(".stat-icons-more")?.textContent).toBe("+");
      expect(el.textContent).toContain("0–20 Armor");
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
    it("renders every condition on a drop, with the wikitext stripped", () => {
      const dropSection = requireItem(
        zombie.sections.find((s): s is DropTable => s.type === "DropTable"),
        "DropTable",
      );

      const el = requireItem(renderDropTable(dropSection, ctx), "DropTable element");
      const rows = el.querySelectorAll("tbody tr");

      // A note the wiki splits by edition. The pipeline keeps the Java side, so
      // the Bedrock wording ("spawned as a zombie horseman") must not appear.
      const mushroomRow = requireItem(
        Array.from(rows).find((r) => r.textContent.includes("Red Mushroom")),
        "Red Mushroom row",
      );
      const mushroomNote = requireItem(
        mushroomRow.querySelector(".drop-note"),
        "Red Mushroom note",
      );
      expect(mushroomNote.textContent).toBe("Only if riding a zombie horse.");
      expect(el.textContent).not.toContain("zombie horseman");

      // A drop can carry more than one condition, and both are shown.
      const potatoRow = requireItem(
        Array.from(rows).find((r) => r.textContent.includes("Potato")),
        "Potato row",
      );
      const potatoNotes = Array.from(potatoRow.querySelectorAll(".drop-note")).map(
        (n) => n.textContent,
      );
      expect(potatoNotes).toHaveLength(2);

      // The wiki's emphasis markup is quote runs, and it must not reach the page.
      expect(el.textContent).not.toContain("''");
      expect(potatoNotes[1]).toContain("not on fire");
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

      // Descriptions: both gameDescription and requirements description are rendered
      const descs = el.querySelectorAll(".advancement-description");
      expect(descs.length).toBe(2);

      expect(descs[0]?.textContent).toBe(
        "Sneak near a Sculk Sensor or Warden to prevent it from detecting you",
      );

      // Requirements description renders with live entity links
      expect(descs[1]?.textContent).toContain(
        "Sneak while causing a vibration within 8 blocks of a",
      );
      const reqLinks = descs[1]?.querySelectorAll(".entity-link");
      expect(reqLinks?.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("BreedingInfo", () => {
    it("renders untamed mob breeding section with default 20 minutes baby growth", () => {
      const section: BreedingInfo = {
        type: "BreedingInfo",
        items: [{ name: "Wheat", ref: { id: "minecraft:wheat", name: "Wheat" } }],
        requiresTaming: false,
        tamingItems: [],
        cooldownSeconds: 300,
        babyGrowthSeconds: 1200,
      };

      const el = requireItem(renderBreedingInfo(section, ctx), "BreedingInfo element");

      expect(el.querySelector(".section-title")?.textContent).toBe("Breeding");
      expect(el.querySelector(".stat-badge")).toBeNull();

      const timingText = el.querySelector(".breeding-timing")?.textContent ?? "";
      expect(timingText).toContain("Cooldown: 5 minutes");
      expect(timingText).toContain("Baby Growth: 20 minutes");

      const foodItems = el.querySelectorAll(".breeding-items .entity-link");
      expect(foodItems.length).toBe(1);
      expect(foodItems[0]?.textContent).toContain("Wheat");

      expect(el.querySelector(".taming-group")).toBeNull();
    });

    it("renders tamed mob with requires taming badge and separated taming items", () => {
      const section: BreedingInfo = {
        type: "BreedingInfo",
        items: [
          { name: "Raw Beef", ref: { id: "minecraft:beef", name: "Raw Beef" } },
          { name: "Porkchop", ref: { id: "minecraft:porkchop", name: "Porkchop" } },
        ],
        requiresTaming: true,
        tamingItems: [{ name: "Bone", ref: { id: "minecraft:bone", name: "Bone" } }],
        cooldownSeconds: 300,
        babyGrowthSeconds: 1200,
      };

      const el = requireItem(renderBreedingInfo(section, ctx), "BreedingInfo element");

      const badge = el.querySelector(".stat-badge");
      expect(badge?.textContent).toBe("Requires Taming");

      const foodItems = Array.from(el.querySelectorAll(".breeding-items .entity-link"));
      const foodNames = foodItems.map((item) => item.textContent);
      expect(foodNames.some((n) => n.includes("Porkchop"))).toBe(true);
      expect(foodNames.some((n) => n.includes("Bone"))).toBe(false);

      const tamingGroup = requireItem(el.querySelector(".taming-group"), "taming group");
      const tamingItems = Array.from(tamingGroup.querySelectorAll(".entity-link"));
      const tamingNames = tamingItems.map((item) => item.textContent);
      expect(tamingNames.some((n) => n.includes("Bone"))).toBe(true);
      expect(tamingNames.some((n) => n.includes("Porkchop"))).toBe(false);
    });

    it("renders the section's own baby growth time, not one inferred from the food list", () => {
      const sniffer: BreedingInfo = {
        type: "BreedingInfo",
        items: [{ name: "Torchflower Seeds" }],
        requiresTaming: false,
        tamingItems: [],
        cooldownSeconds: 300,
        babyGrowthSeconds: 2400,
      };

      const snifferEl = requireItem(renderBreedingInfo(sniffer, ctx), "Sniffer BreedingInfo");
      const snifferTiming = snifferEl.querySelector(".breeding-timing")?.textContent ?? "";
      expect(snifferTiming).toContain("Baby Growth: 40 minutes");

      // A chicken eats Torchflower Seeds too, but grows up in the usual 20 minutes.
      // Reading the food list instead of the field is what got this wrong before.
      const chicken: BreedingInfo = {
        type: "BreedingInfo",
        items: [{ name: "Wheat Seeds" }, { name: "Torchflower Seeds" }],
        requiresTaming: false,
        tamingItems: [],
        cooldownSeconds: 300,
        babyGrowthSeconds: 1200,
      };

      const chickenEl = requireItem(renderBreedingInfo(chicken, ctx), "Chicken BreedingInfo");
      const chickenTiming = chickenEl.querySelector(".breeding-timing")?.textContent ?? "";
      expect(chickenTiming).toContain("Baby Growth: 20 minutes");
      expect(chickenTiming).not.toContain("40 minutes");
    });

    it("returns null when items is empty", () => {
      const section: BreedingInfo = {
        type: "BreedingInfo",
        items: [],
        requiresTaming: false,
        tamingItems: [],
        cooldownSeconds: 300,
        babyGrowthSeconds: 1200,
      };

      expect(renderBreedingInfo(section, ctx)).toBeNull();
    });
  });
});
