# Web App Architecture & Frontend

## Non-negotiables

1. **Keyboard first.** Every action reachable without a mouse. The mouse is a fallback, not the path.
2. **Speed is the feature.** Budget: keystroke to updated suggestion list under 16 ms; Enter to rendered window under 100 ms. No network round trip on the hot path — search runs against a preloaded local index.
3. **No UI framework.** Vanilla TypeScript + Vite. Plain HTML, CSS, JS. No runtime React/Vue weight.

## The Entity Model

Everything searchable is an `Entity`, discriminated by `kind`:
`mob | item | block | effect | advancement | enchantment | structure | biome | collection`.

Shared fields: `id` (namespaced, e.g. `minecraft:creeper` or `collection:compostable`), `name`, `aliases[]`, `icon`, `blurb`, `wikiUrl`, `sections[]`, `sourceTiers`.

`sections[]` is an ordered discriminated union of render blocks — `StatBlock`, `SpawnInfo`, `DropTable`, `RecipeTree`, `ObtainList`, `BreedingInfo`, `EffectSources`, `AdvancementInfo`, `TradeTable`, `ChestLoot`, `EnchantInfo`, `GenerationInfo`, `LinkList`.

### Recipe Trees

Item pages show a single obtain-tree rooted at the item. Brewing is part of this tree. Cycles are detected and cut; memoized by item ID within a single tree; default depth is 3; repeated subtrees collapse to back-references.

## Sprites & Icons

Icons come from the wiki via `spritefile` bucket (`Invicon <Name>.png`, `BlockSprite <id>.png`, `EntitySprite <id>.png`, `EffectSprite <id>.png`). Packed into a single atlas at build time (`data/sprites.png` + `data/sprites.json`). Rendered with `image-rendering: pixelated`.

## Deployment

Static output deployed to any static host (Cloudflare Pages recommended, GitHub Pages, etc.).
Shipped files:
- `index.html`
- `assets/app-<hash>.js`
- `assets/app-<hash>.css`
- `data/index.json`
- `data/entities/<shard>.json`
- `data/sprites.png`
- `data/sprites.json`
- `data/manifest.json`
