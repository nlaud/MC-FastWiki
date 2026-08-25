// Generated from pipeline/schema/manifest.schema.json. Do not edit.
//
// Run `pnpm schema:types` after a change to that schema. `pnpm build` runs
// the same command, and `pnpm test` fails when this file is out of date.

/**
 * data/manifest.json. It names the build, and `python -m pipeline check` reads it to decide whether a rebuild is needed.
 */
export interface Manifest {
  /**
   * The version of this contract. The web app refuses data that carries another number. Raise it whenever a schema change breaks an older reader.
   */
  schemaVersion: 1;
  /**
   * The Minecraft Java Edition release that this build describes. The value comes from the Mojang version manifest.
   */
  minecraftVersion: string;
  /**
   * The misode/mcmeta tag that the build read. A tag keeps the build reproducible, and a bare branch head does not.
   */
  mcmetaRef: string;
  /**
   * The version of the pipeline package that wrote this output.
   */
  pipelineVersion: string;
  /**
   * The time of the build, in UTC.
   */
  builtAt: string;
}
