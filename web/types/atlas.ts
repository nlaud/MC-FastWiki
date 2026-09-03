// Generated from pipeline/schema/atlas.schema.json. Do not edit.
//
// Run `pnpm schema:types` after a change to that schema. `pnpm build` runs
// the same command, and `pnpm test` fails when this file is out of date.

/**
 * A sprite key: the sprite family the wiki's spritefile bucket uses (InvSprite, EntitySprite, ...), a colon, and the sprite id that bucket row names. Mirrors the shape entity.schema.json's icon field already carries. The id half is not a namespaced identifier the way an entityId is: pipeline.enrich.sprite reads it verbatim from the wiki's own id column, which for the InvSprite family is a display name ("Raw Iron"), not a lowercase, hyphenated slug -- so this pattern only fixes the family half's shape and requires the id half to be non-empty.
 *
 * This interface was referenced by `Atlas`'s JSON-Schema
 * via the `definition` "iconKey".
 */
export type IconKey = string;

/**
 * data/dist/sprites.json, the coordinate map into data/dist/sprites.png, the single packed image every entity icon is cropped from. `pipeline.emit.atlas` builds this file from a `pipeline.enrich.sprite.SpriteIndex` lookup over a build's entities -- see that module's own docstring for the shelf-packing algorithm and for why it is deterministic. `sprites` is keyed by the icon key `entity.schema.json`'s own `icon` field already carries ("InvSprite:Raw Iron"), not by the wiki `File:` title the pixels came from, so the web app crops a sprite straight out of `image` with no second lookup.
 */
export interface Atlas {
  /**
   * The version of this contract. The web app refuses data that carries another number. Raise it whenever a schema change breaks an older reader.
   */
  schemaVersion: 1;
  /**
   * The file name of the packed atlas image under data/dist/, sibling to this file. Always "sprites.png" today.
   */
  image: string;
  /**
   * The atlas image's width in pixels.
   */
  width: number;
  /**
   * The atlas image's height in pixels. The exact sum of every packed shelf row's height -- never padded and never rounded to a power of two, because the atlas is read as a plain image and never bound as a GPU texture.
   */
  height: number;
  /**
   * Every icon key this build resolved, mapped to its rectangle within the atlas image. Several icon keys may share one rectangle, when more than one entity's icon names the same wiki File: page.
   */
  sprites: {
    [k: string]: SpriteFrame;
  };
}
/**
 * One sprite's rectangle within the atlas image, in pixels, top-left origin.
 *
 * This interface was referenced by `Atlas`'s JSON-Schema
 * via the `definition` "spriteFrame".
 */
export interface SpriteFrame {
  /**
   * The left edge of the sprite's rectangle, in pixels from the atlas image's left edge.
   */
  x: number;
  /**
   * The top edge of the sprite's rectangle, in pixels from the atlas image's top edge.
   */
  y: number;
  /**
   * The width of the sprite's rectangle, in pixels.
   */
  w: number;
  /**
   * The height of the sprite's rectangle, in pixels.
   */
  h: number;
}
