# The mcmeta fallback

`README.md` states the first build rule of this repository: nothing here needs Java. The pipeline
reads `misode/mcmeta`, which runs Mojang's data generator for each Minecraft version and publishes
the output as JSON.

That rule holds while mcmeta tags each release. This document is the escape hatch for the day
mcmeta lags a release. It describes work that one person does by hand, one time. It is not a step
of the build. No code in this repository runs it, and this document does not ask anyone to write
that code.

## When to use the hatch

Use the hatch only when both of these are true.

1. mcmeta holds no tag for a Minecraft version that Mojang has released.
2. The wait for that tag costs more than the work below.

People skip the second condition. Read the next two sections before you install a JDK.

## Do nothing first

The pipeline pins one version, and `/data/dist` holds the output of the last build. The site keeps
serving that output. A missing tag stops a rebuild. It does not break the deployed site.

mcmeta has published within hours of every release so far. A wait of one day costs nothing. Look at
the tag list again the next day. Use the hatch only after the wait becomes real.

## The failure signal

`resolve_mcmeta_tag` in `pipeline/fetch/mcmeta.py` asks the GitHub single-reference endpoint for
one exact tag. The tag name is `<version>-<branch>`:

```
https://api.github.com/repos/misode/mcmeta/git/ref/tags/26.2-data
```

GitHub answers 404 when that tag does not exist. `get_bytes` then raises `FetchError`, and the
message names the URL above.

A build resolves two tags, one for each branch it reads: `26.2-data` and `26.2-summary`. mcmeta
tags each branch on its own, so take the tag out of the message rather than assuming the branch.
One of the two can be there while the other is not.

A near miss cannot pin the wrong tag, because this endpoint matches one exact name and never a
prefix. A spent rate limit answers 403 or 429, so it does not look like this either. Two other
faults do look exactly like this, and both cost far less to repair than the hatch:

1. **The repository moved.** GitHub answers 404 for a repository it will not show you, so a rename,
   a delete, or a switch to private reads the same as a missing tag. The repair is
   `MCMETA_REPOSITORY`, not a JDK.
2. **The version ID is wrong.** `resolve_mcmeta_tag` takes that ID as an argument, so a hand-typed
   version that Mojang never released asks for a tag that nobody ever wrote.

Read the answers yourself before you go further. Replace `26.2-data` with the tag from the message:

```sh
curl -s -o /dev/null -w '%{http_code}\n' https://api.github.com/repos/misode/mcmeta
curl -s -o /dev/null -w '%{http_code}\n' \
  https://api.github.com/repos/misode/mcmeta/git/ref/tags/26.2-data
```

The first line answers `200` while the repository sits where this pipeline looks for it. A `404`
there is fault 1, and the hatch is the wrong tool for it. On the second line, `404` means the tag
is absent, and `200` means the tag is there and the fault is somewhere else.

## Run the generator

Do these steps on one machine.

1. Find the version in the Mojang version manifest. The manifest holds no jar URL. Each entry of
   `versions` carries a `url`, and that URL names the JSON of that one version.
   `pipeline.fetch.version_manifest.VersionEntry` drops the field, so read it by hand.
2. Read `javaVersion.majorVersion` of that JSON. It names the JDK that the version needs. Install
   that JDK.
3. Read `downloads.server.url` of the same JSON, and download the jar.
4. Run the generator with the command below.
5. Read the output under `generated/`.

```sh
java -DbundlerMainClass=net.minecraft.data.Main -jar server.jar --all --output generated
```

The server jar is a bundler. `-DbundlerMainClass` names the class inside it that the JVM starts.

Mojang changes these flags between versions. Check the flags of the version in hand with `--help`
before you trust the line above.

## Map the output onto the pipeline

The pipeline makes two reads of mcmeta. One read maps onto the generator output. The other read
does not.

### The data half maps path for path

`fetch_data_files` keys every file it returns by the path under `data/minecraft/`, such as
`recipe/oak_stairs.json`. `DATA_GROUPS` names the seven groups that the pipeline reads:

- `advancement`
- `loot_table`
- `recipe`
- `tags`
- `worldgen/biome`
- `worldgen/configured_feature`
- `worldgen/placed_feature`

The generator writes that same tree under `generated/data/minecraft/`, so no path changes here.

What the reader takes is not a tree. `fetch_data_files` reads one gzip archive of a whole commit,
and `read_data_archive` unwraps it: every member sits under one root directory, and the path under
that root must start with `data/minecraft/<group>/`. So pack the `generated` directory itself, and
let its name be that root:

```sh
tar -czf mcmeta-data.tar.gz generated
```

Do not pack `generated/data`. The reader strips the root directory of the archive, so each member
would then read as `minecraft/recipe/...` and match no group. Every file is skipped, and the read
raises `FetchError` to say that the archive holds no file under `data/minecraft/advancement/` or
the other three prefixes — which is the message this pipeline gives for a broken scrape.

### Hand the payload to the reader

Neither half needs new fetch code. Both readers take a `transport`, which is the callable that
returns the bytes of one URL, so a transport that answers from the disk carries the local payload
in:

- `fetch_data_files(tag, transport=...)` for the archive above.
- `fetch_summary_payload(tag, name, transport=...)` for each of the three files below.

`read_data_archive(payload, source=...)` is pure, so it also takes the bytes on their own.

`tag` is a `McmetaTag`. A hand run has no commit to resolve, so build that model rather than calling
`resolve_mcmeta_tag`. Keep one rule in view: `commit_sha` holds 40 hexadecimal characters, and the
model refuses every other value, so a placeholder such as `local` raises `ValidationError` rather
than `FetchError`. Name the payload by its own content hash instead. `git hash-object` writes 40
hexadecimal characters, and that name changes when the payload changes. The commit SHA sits inside
the URL that the cache under `/data/.cache` keys on, so a second run of a changed payload gets a
new key rather than the first payload back.

### The summary half needs a reshape

`fetch_summary_payload` reads three files of the `summary` branch:

| Name | Path on the branch |
| --- | --- |
| `blocks` | `blocks/data.json` |
| `item_components` | `item_components/data.json` |
| `registries` | `registries/data.json` |

The generator writes none of those three files. It writes reports under `generated/reports/` in its
own shape, and mcmeta condenses each report into the file above.

**That reshape is the whole cost of the hatch.** The person who runs the hatch must write it. Read
the build scripts of `misode/mcmeta` for the current shape of each file. Compare the shape against
the report in hand, because the report names and their contents also change between versions.

Keep one trap in view. The keys of `item_components` carry no namespace. The key is `apple`, not
`minecraft:apple`. A prefixed lookup returns nothing and reports nothing. `CLAUDE.md` names this
trap, and the comment above `SUMMARY_PAYLOADS` repeats it.

## Two rules that stay

1. The hatch runs by hand, on one machine, one time. Remove the JDK after the release.
2. CI never runs the hatch. `python -m pipeline build` never starts a JVM.

Do not build the hatch into the pipeline. mcmeta has lagged no release so far. Code that nobody
runs rots, and this code would carry a JVM dependency into a repository whose first build rule is
that it has none.
