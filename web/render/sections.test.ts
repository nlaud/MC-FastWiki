import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type {
  AdvancementInfo,
  BreedingInfo,
  DropTable,
  Entity,
  FoodInfo,
  HarvestInfo,
  RecipeTree,
  SpawnInfo,
  StatBlock,
  TradeTable,
} from "../types/entity.js";
import type { Index, IndexEntry } from "../types/index.js";
import type { Obtain, ObtainProducer } from "../types/obtain.js";
import type { RenderContext } from "./context.js";
import { buildObtainTree } from "./obtain-tree.js";
import { renderAdvancementInfo } from "./sections/advancement-info.js";
import { renderBreedingInfo } from "./sections/breeding-info.js";
import { renderDropTable } from "./sections/drop-table.js";
import { renderFoodInfo } from "./sections/food-info.js";
import { renderHarvestInfo } from "./sections/harvest-info.js";
import { formatOdds, renderRecipeTree } from "./sections/recipe-tree.js";
import { renderSpawnInfo } from "./sections/spawn-info.js";
import { renderStatBlock } from "./sections/stat-block.js";
import { renderTradeTable } from "./sections/trade-table.js";
import { advanceTickerForTesting, resetTickerForTesting } from "./station/ticker.js";

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

  /** Every item entity of the committed build, across all item shards. */
  let itemsById: Map<string, Entity>;
  let blocksById: Map<string, Entity>;
  let obtainGraph: Obtain;

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

    // The food section lands on items spread across three shards, so this
    // reads them all rather than guessing which shard holds the milk bucket.
    itemsById = new Map<string, Entity>();
    for (const shard of ["item-0", "item-1", "item-2"]) {
      const raw = fs.readFileSync(
        path.resolve(process.cwd(), `data/dist/entities/${shard}.json`),
        "utf8",
      );
      for (const entity of (JSON.parse(raw) as { entities: Entity[] }).entities) {
        itemsById.set(entity.id, entity);
      }
    }

    const block0Raw = fs.readFileSync(
      path.resolve(process.cwd(), "data/dist/entities/block-0.json"),
      "utf8",
    );
    blocksById = new Map<string, Entity>();
    for (const entity of (JSON.parse(block0Raw) as { entities: Entity[] }).entities) {
      blocksById.set(entity.id, entity);
    }

    const obtainRaw = fs.readFileSync(path.resolve(process.cwd(), "data/dist/obtain.json"), "utf8");
    obtainGraph = JSON.parse(obtainRaw) as Obtain;

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
  describe("FoodInfo", () => {
    const foodSectionOf = (id: string): FoodInfo => {
      const entity = requireItem(itemsById.get(id), id);
      const section = entity.sections.find((s) => s.type === "FoodInfo");
      return requireItem(section, `${id} FoodInfo`);
    };

    it("is the first section of a food item, so it renders directly under the blurb", () => {
      // TODO.md's Phase 6 line asks for this block "right after the blurb at
      // the top of the page". `web/render/entity.ts` draws sections in array
      // order, so position in the array is the whole of that guarantee.
      const rottenFlesh = requireItem(itemsById.get("minecraft:rotten_flesh"), "Rotten Flesh");
      expect(rottenFlesh.sections[0]?.type).toBe("FoodInfo");
    });

    it("draws hunger as real shank sprites, one per two points", () => {
      const el = requireItem(renderFoodInfo(foodSectionOf("minecraft:rotten_flesh"), ctx), "el");

      const icons = el.querySelectorAll(".food-icons .entity-icon");
      expect(icons).toHaveLength(2);
      // Real atlas keys, not hand-drawn SVG: the sprites exist, so the
      // renderer uses them.
      expect(icons[0]?.getAttribute("data-icon")).toBe("HudSprite:hunger-full");
      expect(el.querySelector(".food-hunger")?.textContent).toBe("4 hunger");
    });

    it("prints saturation with no float32 noise", () => {
      const el = requireItem(renderFoodInfo(foodSectionOf("minecraft:beef"), ctx), "el");
      // Upstream this value is 1.8000001.
      expect(el.querySelector(".food-saturation")?.textContent).toBe("1.8 saturation");
    });

    it("formats an effect duration as m:ss and links the effect", () => {
      const el = requireItem(renderFoodInfo(foodSectionOf("minecraft:rotten_flesh"), ctx), "el");

      const row = requireItem(el.querySelector(".food-effect-row"), "effect row");
      const link = requireItem(
        row.querySelector<HTMLAnchorElement>("a.entity-link"),
        "effect link",
      );
      expect(link.textContent).toContain("Hunger");
      expect(link.dataset["id"]).toBe("minecraft:hunger");
      // 600 ticks.
      expect(row.querySelector(".food-effect-duration")?.textContent).toBe("0:30");
    });

    it("shows a probability only when the effect is not certain", () => {
      const gamble = requireItem(renderFoodInfo(foodSectionOf("minecraft:rotten_flesh"), ctx), "a");
      expect(gamble.querySelector(".food-effect-chance")?.textContent).toBe("80% chance");

      const certain = requireItem(renderFoodInfo(foodSectionOf("minecraft:spider_eye"), ctx), "b");
      expect(certain.querySelector(".food-effect-chance")).toBeNull();
    });

    it("writes a Roman level only above level I", () => {
      const el = requireItem(renderFoodInfo(foodSectionOf("minecraft:golden_apple"), ctx), "el");
      const rows = el.querySelectorAll(".food-effect-row");

      // Regeneration is amplifier 1 upstream, so level II on screen.
      expect(rows[0]?.textContent).toContain("Regeneration II");
      // Absorption is amplifier 0, and carries no numeral at all.
      expect(rows[1]?.textContent).toContain("Absorption");
      expect(rows[1]?.textContent).not.toContain("Absorption I");
    });

    it("badges an item that can be eaten on a full hunger bar", () => {
      const golden = requireItem(renderFoodInfo(foodSectionOf("minecraft:golden_apple"), ctx), "a");
      expect(golden.querySelector(".food-always-badge")?.textContent).toBe("Always edible");

      const flesh = requireItem(renderFoodInfo(foodSectionOf("minecraft:rotten_flesh"), ctx), "b");
      expect(flesh.querySelector(".food-always-badge")).toBeNull();
    });

    it("heads a consumable that restores no hunger as Consuming, not Food", () => {
      // The milk bucket is the one item in 26.2 that reaches this branch.
      const el = requireItem(renderFoodInfo(foodSectionOf("minecraft:milk_bucket"), ctx), "el");

      expect(el.querySelector(".section-title")?.textContent).toBe("Consuming");
      expect(el.querySelector(".food-hunger")).toBeNull();
      expect(el.textContent).toContain("Removes every active status effect.");
    });

    it("names the effect a cure removes, as a link", () => {
      const el = requireItem(renderFoodInfo(foodSectionOf("minecraft:honey_bottle"), ctx), "el");

      expect(el.textContent).toContain("Cures");
      const link = requireItem(
        el.querySelector<HTMLAnchorElement>("a.entity-link"),
        "cured effect link",
      );
      expect(link.dataset["id"]).toBe("minecraft:poison");
    });

    it("states the chorus fruit's teleport", () => {
      const el = requireItem(renderFoodInfo(foodSectionOf("minecraft:chorus_fruit"), ctx), "el");
      expect(el.textContent).toContain("Teleports");
    });

    it("returns null for a section carrying nothing at all", () => {
      const empty: FoodInfo = {
        type: "FoodInfo",
        canAlwaysEat: false,
        effects: [],
        removes: [],
        clearsAllEffects: false,
        teleportsRandomly: false,
      };

      expect(renderFoodInfo(empty, ctx)).toBeNull();
    });
  });

  describe("renderHarvestInfo", () => {
    it("renders tool, tier, and dropsWithoutTool correctly for chiseled_bookshelf", () => {
      const bookshelf = requireItem(
        blocksById.get("minecraft:chiseled_bookshelf"),
        "Chiseled Bookshelf",
      );
      const harvestSection = requireItem(
        bookshelf.sections.find((s): s is HarvestInfo => s.type === "HarvestInfo"),
        "HarvestInfo",
      );
      const el = requireItem(renderHarvestInfo(harvestSection, ctx), "HarvestInfo element");

      expect(el.querySelector(".section-title")?.textContent).toBe("Harvest");
      expect(el.textContent).toContain("Axe");
      expect(el.textContent).toContain("Wooden (any)");
      expect(el.querySelector(".badge-yes")?.textContent).toBe("Yes");
    });

    it("renders dropsWithoutTool as No for pickaxe blocks", () => {
      const anvil = requireItem(blocksById.get("minecraft:chipped_anvil"), "Chipped Anvil");
      const harvestSection = requireItem(
        anvil.sections.find((s): s is HarvestInfo => s.type === "HarvestInfo"),
        "HarvestInfo",
      );
      const el = requireItem(renderHarvestInfo(harvestSection, ctx), "HarvestInfo element");

      expect(el.textContent).toContain("Pickaxe");
      expect(el.querySelector(".badge-no")?.textContent).toBe("No");
    });

    it("renders minimum tier above wooden without the (any) suffix", () => {
      const copper = requireItem(blocksById.get("minecraft:chiseled_copper"), "Chiseled Copper");
      const harvestSection = requireItem(
        copper.sections.find((s): s is HarvestInfo => s.type === "HarvestInfo"),
        "HarvestInfo",
      );
      const el = requireItem(renderHarvestInfo(harvestSection, ctx), "HarvestInfo element");

      expect(el.textContent).toContain("Stone");
      expect(el.textContent).not.toContain("Stone (any)");
    });

    it("links every drop and badges only the silk touch ones", () => {
      const harvestSection: HarvestInfo = {
        type: "HarvestInfo",
        tools: ["pickaxe"],
        tier: "iron",
        dropsWithoutTool: false,
        drops: [
          { id: "minecraft:diamond_ore", name: "Diamond Ore", count: 1, silkTouch: true },
          { id: "minecraft:diamond", name: "Diamond", count: 1, silkTouch: false },
        ],
      };
      const el = requireItem(renderHarvestInfo(harvestSection, ctx), "HarvestInfo element");

      expect(el.textContent).toContain("Drops");
      const links = el.querySelectorAll(".entity-link");
      expect(links.length).toBe(2);
      // The plain drop sorts ahead of the silk-touch one whatever order it arrived in.
      expect(requireItem(links[0], "first link").textContent).toBe("Diamond");
      expect(requireItem(links[1], "second link").textContent).toBe("Diamond Ore");

      const badges = el.querySelectorAll(".sources-note-badge");
      expect(badges.length).toBe(1);
      expect(requireItem(badges[0], "silk touch badge").textContent).toBe("requires silk touch");
      const badged = requireItem(
        requireItem(badges[0], "silk touch badge").closest(".harvest-drop"),
        "badged drop",
      );
      expect(requireItem(badged.querySelector(".entity-name"), "badged name").textContent).toBe(
        "Diamond Ore",
      );
    });

    it("prints a drop count above one and omits it at one", () => {
      const harvestSection: HarvestInfo = {
        type: "HarvestInfo",
        tools: ["pickaxe"],
        tier: "iron",
        dropsWithoutTool: false,
        drops: [
          { id: "minecraft:redstone", name: "Redstone Dust", count: 4, silkTouch: false },
          { id: "minecraft:diamond", name: "Diamond", count: 1, silkTouch: false },
        ],
      };
      const el = requireItem(renderHarvestInfo(harvestSection, ctx), "HarvestInfo element");

      const quantities = el.querySelectorAll(".item-quantity");
      expect(quantities.length).toBe(1);
      expect(requireItem(quantities[0], "quantity").textContent).toBe("4 ");
    });

    it("omits the drops row when the section carries none", () => {
      const harvestSection: HarvestInfo = {
        type: "HarvestInfo",
        tools: ["pickaxe"],
        tier: "iron",
        dropsWithoutTool: false,
        drops: [],
      };
      const el = requireItem(renderHarvestInfo(harvestSection, ctx), "HarvestInfo element");

      expect(el.querySelector(".harvest-drops")).toBeNull();
    });
  });

  describe("renderRecipeTree", () => {
    it("renders Obtaining heading with workstation tree and sources panes", () => {
      const tree = buildObtainTree("minecraft:iron_ingot", obtainGraph);
      const section = {
        type: "RecipeTree",
        root: tree.root,
        rawProducers: tree.rawProducers,
        sources: tree.sources,
      } as unknown as RecipeTree;
      const el = requireItem(renderRecipeTree(section, ctx), "RecipeTree element");

      expect(el.querySelector(".section-title")?.textContent).toBe("Obtaining");
      expect(el.querySelector(".obtaining-shell")).not.toBeNull();
      expect(el.querySelector(".obtaining-tree-pane")).not.toBeNull();
      expect(el.querySelector(".obtaining-sources-pane")).not.toBeNull();

      // Station cards should be present in the tree pane
      const cards = el.querySelectorAll(".obtaining-tree-pane .station-card");
      expect(cards.length).toBeGreaterThan(0);
    });

    // The Crafting Table is made from any four planks, so its plank slot cycles
    // through twelve woods. The branch under that slot used to be built once,
    // from the tag's representative member, so the slot advanced to Spruce while
    // the log below it stayed Oak forever.
    it("advances a tag branch in step with the slot above it", () => {
      resetTickerForTesting();
      const tree = buildObtainTree("minecraft:crafting_table", obtainGraph);
      const section = {
        type: "RecipeTree",
        root: tree.root,
        rawProducers: tree.rawProducers,
        sources: tree.sources,
        graph: obtainGraph,
      } as unknown as RecipeTree;
      const el = requireItem(renderRecipeTree(section, ctx), "RecipeTree element");

      const branchItems = (): (string | null)[] =>
        Array.from(el.querySelectorAll(".tree-branch .leaf-name")).map((n) => n.textContent);

      const before = branchItems();
      expect(before.length).toBeGreaterThan(0);

      // Enough ticks to pass every member of a twelve-wood tag.
      const seen = new Set(before);
      for (let i = 0; i < 12; i++) {
        advanceTickerForTesting();
        for (const name of branchItems()) {
          seen.add(name);
        }
      }

      expect(seen.size).toBeGreaterThan(before.length);
      resetTickerForTesting();
    });

    it("renders chest loot sources in Title Case without links", () => {
      const tree = buildObtainTree("minecraft:emerald", obtainGraph);
      const section = {
        type: "RecipeTree",
        root: tree.root,
        rawProducers: tree.rawProducers,
        sources: tree.sources,
      } as unknown as RecipeTree;
      const el = requireItem(renderRecipeTree(section, ctx), "RecipeTree element");

      const labels = Array.from(el.querySelectorAll(".sources-chest-label")).map(
        (e) => e.textContent,
      );
      expect(labels.length).toBeGreaterThan(0);

      // Curated chest sources are in Title Case
      for (const label of labels) {
        expect(label).toBeTruthy();
        if (label) {
          const words = label.split(/[\s\-()]+/);
          for (const w of words) {
            const firstChar = w[0];
            if (firstChar) {
              expect(firstChar).toBe(firstChar.toUpperCase());
            }
          }
        }
      }

      // No anchor links in chest loot group (Decision 1)
      const chestGroup = el.querySelector(".sources-chest-group");
      expect(chestGroup?.querySelectorAll("a")).toHaveLength(0);
    });

    it("shows up to 3 sources per group with remainder behind toggle button", () => {
      const tree = buildObtainTree("minecraft:iron_ingot", obtainGraph);
      const section = {
        type: "RecipeTree",
        root: tree.root,
        rawProducers: tree.rawProducers,
        sources: tree.sources,
      } as unknown as RecipeTree;
      const el = requireItem(renderRecipeTree(section, ctx), "RecipeTree element");

      // Iron ingot has many chest_loot producers (> 3)
      const moreBtn = el.querySelector<HTMLButtonElement>(".sources-more-button");
      expect(moreBtn).not.toBeNull();
      expect(moreBtn?.textContent).toMatch(/Show \d+ more/i);

      const overflow = el.querySelector<HTMLElement>(".sources-overflow");
      expect(overflow?.hidden).toBe(true);
      expect(overflow?.querySelectorAll(".sources-item").length).toBe(0);

      moreBtn?.click();
      expect(overflow?.hidden).toBe(false);
      expect(overflow?.querySelectorAll(".sources-item").length).toBeGreaterThan(0);
      expect(moreBtn?.textContent).toMatch(/Show fewer/i);

      // Collapsing keeps the rows already built
      const builtRows = overflow?.querySelectorAll(".sources-item").length;
      moreBtn?.click();
      expect(overflow?.hidden).toBe(true);
      expect(overflow?.querySelectorAll(".sources-item").length).toBe(builtRows);
    });

    it("embeds entity trades inside Sources panel and not in the workstation tree", () => {
      const tree = buildObtainTree("minecraft:apple", obtainGraph);
      const section = {
        type: "RecipeTree",
        root: tree.root,
        rawProducers: tree.rawProducers,
        sources: tree.sources,
      } as unknown as RecipeTree;

      const el = requireItem(renderRecipeTree(section, ctx, apple), "RecipeTree element");

      // Trade table is embedded inside sources panel
      const tradeGroup = el.querySelector(".sources-trade-group");
      expect(tradeGroup).not.toBeNull();
      expect(tradeGroup?.querySelector(".trade-table")).not.toBeNull();

      // Tree pane must NOT contain trades
      expect(el.querySelector(".obtaining-tree-pane .trade-table")).toBeNull();
    });

    it("renders brushing, fishing, bartering, gift, shearing, and harvesting source groups", () => {
      // Brushing
      const sherdTree = buildObtainTree("minecraft:angler_pottery_sherd", obtainGraph);
      const sherdSection = {
        type: "RecipeTree",
        root: sherdTree.root,
        rawProducers: sherdTree.rawProducers,
        sources: sherdTree.sources,
      } as unknown as RecipeTree;
      const sherdEl = requireItem(renderRecipeTree(sherdSection, ctx), "Sherd RecipeTree element");
      const brushingGroup = sherdEl.querySelector(".sources-brushing-group");
      expect(brushingGroup).not.toBeNull();
      expect(brushingGroup?.querySelector(".sources-group-title")?.textContent).toBe("Brushing");
      expect(brushingGroup?.textContent).toContain("Ocean Ruins (Warm)");

      // Fishing
      const saddleTree = buildObtainTree("minecraft:saddle", obtainGraph);
      const saddleSection = {
        type: "RecipeTree",
        root: saddleTree.root,
        rawProducers: saddleTree.rawProducers,
        sources: saddleTree.sources,
      } as unknown as RecipeTree;
      const saddleEl = requireItem(
        renderRecipeTree(saddleSection, ctx),
        "Saddle RecipeTree element",
      );
      const fishingGroup = saddleEl.querySelector(".sources-fishing-group");
      expect(fishingGroup).not.toBeNull();
      expect(fishingGroup?.querySelector(".sources-group-title")?.textContent).toBe("Fishing");
      expect(fishingGroup?.textContent).toContain("Fishing - Treasure");

      // Bartering
      const pearlTree = buildObtainTree("minecraft:ender_pearl", obtainGraph);
      const pearlSection = {
        type: "RecipeTree",
        root: pearlTree.root,
        rawProducers: pearlTree.rawProducers,
        sources: pearlTree.sources,
      } as unknown as RecipeTree;
      const pearlEl = requireItem(renderRecipeTree(pearlSection, ctx), "Pearl RecipeTree element");
      const barteringGroup = pearlEl.querySelector(".sources-bartering-group");
      expect(barteringGroup).not.toBeNull();
      expect(barteringGroup?.textContent).toContain("Piglin");
      // The old "bartered for gold ingot" note is gone: the odds say what a
      // barter actually costs and yields, and the label links the piglin.
      expect(barteringGroup?.textContent).not.toContain("bartered for gold ingot");
      expect(barteringGroup?.querySelector(".sources-odds")).not.toBeNull();
      expect(barteringGroup?.textContent).toContain("per gold");

      // Gift & Growth
      const turtleTree = buildObtainTree("minecraft:turtle_scute", obtainGraph);
      const turtleSection = {
        type: "RecipeTree",
        root: turtleTree.root,
        rawProducers: turtleTree.rawProducers,
        sources: turtleTree.sources,
      } as unknown as RecipeTree;
      const turtleEl = requireItem(
        renderRecipeTree(turtleSection, ctx),
        "Turtle RecipeTree element",
      );
      const giftGroup = turtleEl.querySelector(".sources-gift-group");
      expect(giftGroup).not.toBeNull();
      expect(giftGroup?.querySelector(".sources-group-title")?.textContent).toBe("Gifts & Growth");
      expect(turtleEl.querySelector(".sources-gift-label")?.textContent).toBe("Turtle - Growth");

      // Shearing
      const woolTree = buildObtainTree("minecraft:white_wool", obtainGraph);
      const woolSection = {
        type: "RecipeTree",
        root: woolTree.root,
        rawProducers: woolTree.rawProducers,
        sources: woolTree.sources,
      } as unknown as RecipeTree;
      const woolEl = requireItem(renderRecipeTree(woolSection, ctx), "Wool RecipeTree element");
      const shearingGroup = woolEl.querySelector(".sources-shearing-group");
      expect(shearingGroup).not.toBeNull();
      expect(shearingGroup?.querySelector(".sources-group-title")?.textContent).toBe("Shearing");
      expect(woolEl.querySelector(".sources-shearing-label")?.textContent).toBe("White Sheep");

      // Harvesting
      const honeyTree = buildObtainTree("minecraft:honeycomb", obtainGraph);
      const honeySection = {
        type: "RecipeTree",
        root: honeyTree.root,
        rawProducers: honeyTree.rawProducers,
        sources: honeyTree.sources,
      } as unknown as RecipeTree;
      const honeyEl = requireItem(
        renderRecipeTree(honeySection, ctx),
        "Honeycomb RecipeTree element",
      );
      const harvestGroup = honeyEl.querySelector(".sources-harvesting-group");
      expect(harvestGroup).not.toBeNull();
      expect(harvestGroup?.querySelector(".sources-group-title")?.textContent).toBe("Harvesting");
      expect(honeyEl.querySelector(".sources-harvesting-label")?.textContent).toBe(
        "Beehive - Shears",
      );
    });

    it("renders natural generation source group for world_generation producers", () => {
      const graph: Obtain = {
        schemaVersion: 1,
        producers: {
          "minecraft:elytra": [
            {
              m: "world_generation",
              src: "world_generation/end_ship/elytra",
              nt: "in the treasure room",
            },
          ],
        },
        sources: {
          "world_generation/end_ship/elytra": {
            structure: "End Ship",
            container: "Item Frame",
          },
        },
      };
      const tree = buildObtainTree("minecraft:elytra", graph);
      const section = {
        type: "RecipeTree",
        root: tree.root,
        rawProducers: tree.rawProducers,
        sources: tree.sources,
      } as unknown as RecipeTree;
      const el = requireItem(renderRecipeTree(section, ctx), "Elytra RecipeTree element");
      const worldgenGroup = el.querySelector(".sources-worldgen-group");
      expect(worldgenGroup).not.toBeNull();
      expect(worldgenGroup?.querySelector(".sources-group-title")?.textContent).toBe(
        "Natural Generation",
      );
      expect(worldgenGroup?.textContent).toContain("End Ship - Item Frame");
      expect(worldgenGroup?.textContent).toContain("in the treasure room");
    });

    it("orders source groups according to canonical SOURCE_GROUP_ORDER", () => {
      const saddleTree = buildObtainTree("minecraft:saddle", obtainGraph);
      const saddleSection = {
        type: "RecipeTree",
        root: saddleTree.root,
        rawProducers: saddleTree.rawProducers,
        sources: saddleTree.sources,
      } as unknown as RecipeTree;
      const saddleEl = requireItem(
        renderRecipeTree(saddleSection, ctx),
        "Saddle RecipeTree element",
      );

      const groups = Array.from(saddleEl.querySelectorAll(".sources-group"));
      const titles = groups.map((g) => g.querySelector(".sources-group-title")?.textContent);

      // Saddle has chest_loot, mob_loot, trade, and fishing
      expect(titles).toEqual(["Chest Loot", "Fishing", "Mob Drops", "Villager Trades"]);
    });

    it("links a mob drop to the mob, never to the item sharing its id", () => {
      // The chicken mob and the raw chicken item are both `minecraft:chicken`.
      // Looking up the bare id alone found the item, so the Feather page said
      // "Dropped by Raw Chicken" and linked a food item.
      const featherTree = buildObtainTree("minecraft:feather", obtainGraph);
      const featherSection = {
        type: "RecipeTree",
        root: featherTree.root,
        rawProducers: featherTree.rawProducers,
        sources: featherTree.sources,
      } as unknown as RecipeTree;
      const featherEl = requireItem(
        renderRecipeTree(featherSection, ctx),
        "Feather RecipeTree element",
      );

      const mobGroup = featherEl.querySelector(".sources-mob-group");
      expect(mobGroup).not.toBeNull();
      expect(mobGroup?.textContent).toContain("Chicken");
      expect(mobGroup?.textContent).not.toContain("Raw Chicken");

      const link = mobGroup?.querySelector(".entity-link");
      expect(link?.textContent).toBe("Chicken");
    });

    it("links every mob drop row to a mob or entity, or to nothing at all", () => {
      // The whole class the Raw Chicken bug belonged to. Cod, Salmon, Chicken
      // and Rabbit all share an id with their raw meat, and a row that links to
      // an item is wrong however plausible the name looks.
      const itemsWithMobDrops = Object.entries(obtainGraph.producers)
        .filter(([, ps]) => ps.some((p) => p.m === "mob_loot"))
        .map(([id]) => id);
      expect(itemsWithMobDrops.length).toBeGreaterThan(50);

      for (const itemId of itemsWithMobDrops) {
        const tree = buildObtainTree(itemId, obtainGraph);
        const section = {
          type: "RecipeTree",
          root: tree.root,
          rawProducers: tree.rawProducers,
          sources: tree.sources,
        } as unknown as RecipeTree;
        const el = renderRecipeTree(section, ctx);
        const rows = el?.querySelectorAll(".sources-mob-item") ?? [];
        for (const row of Array.from(rows)) {
          const linkedId = row.querySelector(".entity-link")?.getAttribute("data-id");
          if (linkedId === null || linkedId === undefined) {
            continue; // Rendered as plain text, which is the honest fallback.
          }
          const entry = ctx.lookup(linkedId);
          expect(entry, `${itemId} links a mob row to unknown ${linkedId}`).not.toBeNull();
          expect(entry?.k, `${itemId} links a mob row to a ${entry?.k ?? "?"}`).toMatch(
            /^(mob|entity)$/,
          );
        }
      }
    });

    it("renders dispensers, pots, and spawners under Chest Loot", () => {
      const keyTree = buildObtainTree("minecraft:ominous_trial_key", obtainGraph);
      const keySection = {
        type: "RecipeTree",
        root: keyTree.root,
        rawProducers: keyTree.rawProducers,
        sources: keyTree.sources,
      } as unknown as RecipeTree;
      const keyEl = requireItem(renderRecipeTree(keySection, ctx), "Key RecipeTree element");

      const chestGroup = keyEl.querySelector(".sources-chest-group");
      expect(chestGroup).not.toBeNull();
      expect(chestGroup?.querySelector(".sources-group-title")?.textContent).toBe("Chest Loot");
      expect(chestGroup?.textContent).toContain("Trial Chambers - Ominous Trial Spawner");
    });

    it("renders stub with expand button and clicking expands the subtree", async () => {
      const tree = buildObtainTree("minecraft:chiseled_resin_bricks", obtainGraph, {
        maxDepth: 1,
      });
      const section = { type: "RecipeTree", root: tree.root } as unknown as RecipeTree;
      const el = requireItem(renderRecipeTree(section, ctx), "RecipeTree element");

      const expandBtn = el.querySelector<HTMLButtonElement>(".tree-expand-stub-btn");
      expect(expandBtn).not.toBeNull();
      expect(expandBtn?.textContent).toBe("Expand...");

      expandBtn?.click();
      // Wait for async stub expansion
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(el.querySelector(".tree-node")).not.toBeNull();
    });

    it("renders back-reference as text reference and not a second subtree", () => {
      const backRefNode = {
        item: "minecraft:iron_ingot",
        producers: [
          {
            method: "crafting" as const,
            station: null,
            note: null,
            source_id: "test",
            inputs: [
              {
                label: "minecraft:iron_nugget",
                item: "minecraft:iron_nugget",
                tag: null,
                count: 1,
                members: [],
                node: {
                  item: "minecraft:iron_nugget",
                  producers: [],
                  expandable: false,
                  back_reference: "root.producers.0.inputs.0",
                },
              },
            ],
          },
        ],
        expandable: false,
        back_reference: null,
      };
      const section = { type: "RecipeTree", root: backRefNode } as unknown as RecipeTree;
      const el = requireItem(renderRecipeTree(section, ctx), "RecipeTree element");

      const backRefEl = el.querySelector<HTMLElement>(".tree-back-reference");
      expect(backRefEl).not.toBeNull();
      expect(backRefEl?.textContent).toBe("(shown above)");
      expect(backRefEl?.title).toBe("root.producers.0.inputs.0");
      expect(backRefEl?.textContent).not.toContain("producers.0");
    });

    it("falls back to readable text when item sprite is absent", () => {
      const unindexedNode = {
        item: "minecraft:test_item",
        producers: [
          {
            method: "crafting" as const,
            station: null,
            note: null,
            source_id: "test",
            inputs: [
              {
                label: "minecraft:unknown_material",
                item: "minecraft:unknown_material",
                tag: null,
                count: 1,
                members: [],
                node: null,
              },
            ],
          },
        ],
        expandable: false,
        back_reference: null,
      };
      const section = { type: "RecipeTree", root: unindexedNode } as unknown as RecipeTree;
      const el = requireItem(renderRecipeTree(section, ctx), "RecipeTree element");

      expect(el.querySelector(".slot-fallback-text")?.textContent).toBe("Unknown Material");
    });

    it("returns null when root has no producers and no sources", () => {
      const emptyTree = {
        item: "minecraft:bedrock",
        producers: [],
        expandable: false,
        back_reference: null,
      };
      const section = { type: "RecipeTree", root: emptyTree } as unknown as RecipeTree;
      expect(renderRecipeTree(section, ctx)).toBeNull();
    });
  });
});

describe("formatOdds", () => {
  /** A producer carrying only the fields `formatOdds` reads. */
  function producer(fields: Partial<ObtainProducer>): ObtainProducer {
    return { m: "chest_loot", src: "loot_table/chests/test.json", ...fields };
  }

  it("returns null for a producer with no odds", () => {
    expect(formatOdds(producer({ m: "crafting" }))).toBeNull();
  });

  it("returns null when the odds are only half present", () => {
    // The pipeline refuses to emit this, so it can only arrive from a payload
    // written by an older build. Reading it as "no odds" is the safe answer.
    expect(formatOdds(producer({ ch: 0.5 }))).toBeNull();
  });

  it("states a chance, a count range, and a rate named after the method", () => {
    const odds = formatOdds(producer({ m: "bartering", ch: 0.085, c: 8, cx: 16, pa: 1.02 }));
    expect(odds).toEqual({ chance: "8.5%", count: "8-16", rate: "1.0 per gold" });
  });

  it("names the attempt from the method", () => {
    expect(formatOdds(producer({ m: "fishing", ch: 0.167, c: 1, cx: 1, pa: 0.17 }))?.rate).toBe(
      "0.2 per catch",
    );
    expect(formatOdds(producer({ m: "mob_loot", ch: 0.5, c: 1, cx: 1, pa: 0.5 }))?.rate).toBe(
      "0.5 per kill",
    );
  });

  it("drops a chance of exactly one rather than saying 100%", () => {
    // A producer that always fires tells the reader nothing by saying so, but
    // its quantity and its mean still carry information.
    const odds = formatOdds(producer({ m: "block_drop", ch: 1, c: 2, cx: 5, pa: 3.5 }));
    expect(odds?.chance).toBeNull();
    expect(odds?.count).toBe("2-5");
    expect(odds?.rate).toBe("3.5 per block");
  });

  it("renders nothing at all for a certain, fixed, single drop", () => {
    // Breaking one cobblestone gives one cobblestone. "100% 1 1.0 per block"
    // is three ways of saying nothing.
    expect(formatOdds(producer({ m: "block_drop", ch: 1, c: 1, cx: 1, pa: 1 }))).toBeNull();
  });

  it("drops the rate when a certain drop is a fixed stack", () => {
    // The rate could only restate the count, so the count says it once.
    const odds = formatOdds(producer({ m: "block_drop", ch: 1, c: 4, cx: 4, pa: 4 }));
    expect(odds?.count).toBe("4");
    expect(odds?.rate).toBeNull();
  });

  it("shows a floor rather than rounding a rare drop to zero percent", () => {
    // "0.0%" reads as impossible; the drop is rare, not absent.
    expect(formatOdds(producer({ ch: 0.0004, c: 1, cx: 1, pa: 0.0004 }))?.chance).toBe("<0.1%");
  });

  it("uses one decimal place below ten percent and none above", () => {
    expect(formatOdds(producer({ ch: 0.067, c: 1, cx: 1, pa: 0.07 }))?.chance).toBe("6.7%");
    expect(formatOdds(producer({ ch: 0.17, c: 1, cx: 1, pa: 0.17 }))?.chance).toBe("17%");
  });

  it("omits the count when it is a single item", () => {
    expect(formatOdds(producer({ ch: 0.5, c: 1, cx: 1, pa: 0.5 }))?.count).toBeNull();
  });

  it("renders the rate without a denominator for a method it has no noun for", () => {
    expect(formatOdds(producer({ m: "brewing", ch: 0.5, c: 1, cx: 1, pa: 0.5 }))?.rate).toBe("0.5");
  });
});
