"""Validate every document `pipeline.emit.write.emit_build` is about to write against its schema.

`tests/test_schema_contract.py` already checks that `pipeline.normalize.entity`'s Pydantic models
and `entity.schema.json` declare the same shape -- a structural comparison, field name against
field name. That test catches a field renamed, added, or dropped on one side and forgotten on the
other. It cannot catch the thing this module catches: a real, correctly-shaped `Entity` whose
*value* nonetheless breaks the schema's own rules -- a `wikiUrl` that fails `entity.schema.json`'s
pattern, a `sourceTiers` key that names a field the schema does not describe, an entity with no
`sections` at all where the model's own type says the tuple may be empty but the schema, read
freshly against the instance, disagrees. `jsonschema.Draft202012Validator` is what closes that gap:
it validates *instances*, not declarations, against the same five files `pipeline/schema` already
holds as the single contract between the pipeline and the web app.

## Five document kinds, one call each, at the exact shape they will be written in

`GateDocuments` carries the shard payloads, the index, the manifest, and the obtain graph, each
already `model_dump(mode="json", by_alias=True, exclude_none=True)`-ed -- the identical call
`pipeline.emit.write._shard_payload` and its three siblings make. Validating anything else --
the Python `Entity` model directly, or a dump with different flags -- would check a document that
never reaches disk: `by_alias=True` is what turns `wiki_url` into `wikiUrl`, and `exclude_none=True`
is what drops an unset `icon` instead of writing a `null` the schema's closed object never declares
a type for. A validator run over the wrong dump would pass documents this pipeline never ships and
could fail ones it does, in either direction, silently.

Individual `Entity` documents are not carried on `GateDocuments` as a list of their own. They live
inside `GateDocuments.shards`, one shard's `"entities"` array at a time, because that is where
`pipeline.emit.write` already has them the moment it calls the gate -- pulling them back out here
is one iteration over data already in memory, not a second serialisation pass.

## One compiled validator per schema, built once, reused across every instance

`Draft202012Validator(schema)` compiles the schema into a form that can check many instances
without redoing that compilation each time. `validate_conformance` builds exactly five of them --
one per file in `pipeline/schema` -- at the top of one call, and reuses each across every instance
of its kind: 2120 entity dicts against the one entity validator, 15 shard dicts against the one
shard validator, and one instance each against the index, obtain, and manifest validators.
Building a fresh `Draft202012Validator` per instance would recompile the same schema roughly 2140
times for one call over the real build, for no benefit -- the schema does not change between one
entity and the next.

## A bounded failure list, not the first failure and not every failure

`iter_errors` can report far more than one problem per instance, and one call here walks over two
thousand instances. Collecting every failure unbounded risks a report so large it is no longer
readable at the moment a build actually breaks in a structural way -- a bug that touches the shape
every entity shares fails on all 2120 of them, and printing all 2120 lines serves nobody. Stopping
at the *first* failure is worse in the other direction: it hides whether a schema break is a
one-entity anomaly or the whole build, which is exactly the distinction a person fixing the bug
needs first. `DEFAULT_MAX_FAILURES` (20) is the compromise -- enough failures to see the shape of
the problem, capped so the report stays readable -- and `ConformanceReport.truncated_count` keeps
the discarded count honest rather than silently dropping it.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import BaseModel

from pipeline.schema import load_schema

__all__ = [
    "DEFAULT_MAX_FAILURES",
    "ConformanceFailure",
    "ConformanceReport",
    "GateDocuments",
    "validate_conformance",
]

# The five files `pipeline/schema` holds. `pipeline.schema.schema_names` would answer this
# generically, but this module needs exactly these five, in the order the module docstring's
# document-kind table lists them, and a generic read would still leave this module needing to know
# which of the five schemas describes a shard's nested entity and which describes the shard itself
# -- knowledge that has to live here regardless.
_SCHEMA_NAMES = ("entity", "shard", "index", "obtain", "manifest")

DEFAULT_MAX_FAILURES = 20


class GateDocuments(BaseModel, frozen=True):
    """The documents `pipeline.emit.write.emit_build` assembled, before any byte reaches disk.

    Each field already carries the exact `model_dump(mode="json", by_alias=True,
    exclude_none=True)` shape `emit_build` writes -- see the module docstring for why that
    precision matters. `shards` is keyed by shard name (`"item-0"`, matching `Shard.name`) so a
    `ConformanceFailure.document` can name which file a shard-level fault came from.
    """

    shards: Mapping[str, Mapping[str, Any]]
    index: Mapping[str, Any]
    obtain: Mapping[str, Any]
    manifest: Mapping[str, Any]


class ConformanceFailure(BaseModel, frozen=True):
    """One place an instance did not satisfy its schema.

    `document` names which document kind failed -- `"entity"`, `"shard:item-0"`, `"index"`,
    `"obtain"`, or `"manifest"` -- and `entity_id` is set only for an `"entity"` failure, because
    that is the one document kind with an id of its own to name; every other kind is already
    identified by `document` alone. `pointer` is the JSON Pointer (RFC 6901) into the *instance*
    that failed -- `""` for the whole document, `"/sourceTiers/blurb"` for one field of it -- and
    `message` is `jsonschema`'s own explanation of what about that location was wrong.
    """

    document: str
    entity_id: str | None
    pointer: str
    message: str


class ConformanceReport(BaseModel, frozen=True):
    """What one `validate_conformance` call checked, and every failure it found, up to the cap.

    `checked` counts instances per document kind (`{"entity": 2120, "shard": 15, "index": 1,
    "obtain": 1, "manifest": 1}` on the real build), so a report can say how much was actually
    validated even when it found nothing wrong. `truncated_count` is how many more failures existed
    past `max_failures` -- see the module docstring's bounded-list section for why this number is
    kept rather than the failures themselves being dropped silently.
    """

    checked: Mapping[str, int]
    failures: tuple[ConformanceFailure, ...] = ()
    truncated_count: int = 0


def _pointer(error: SchemaValidationError) -> str:
    """Return the RFC 6901 JSON Pointer of `error.absolute_path`, `""` for the document root."""
    segments = [str(part) for part in error.absolute_path]
    return "/" + "/".join(segments) if segments else ""


def validate_conformance(
    documents: GateDocuments, *, max_failures: int = DEFAULT_MAX_FAILURES
) -> ConformanceReport:
    """Validate every document `documents` carries against its schema, and return the report.

    Never raises for a schema failure -- that is `pipeline.validate.ValidationGate`'s call to make,
    once it has this report and `pipeline.validate.regression`'s report both in hand. This function
    only measures.
    """
    validators = {name: Draft202012Validator(load_schema(name)) for name in _SCHEMA_NAMES}
    failures: list[ConformanceFailure] = []
    truncated = 0

    def record(
        document: str, entity_id: str | None, errors: Iterable[SchemaValidationError]
    ) -> None:
        nonlocal truncated
        for error in errors:
            if len(failures) < max_failures:
                failures.append(
                    ConformanceFailure(
                        document=document,
                        entity_id=entity_id,
                        pointer=_pointer(error),
                        message=error.message,
                    )
                )
            else:
                truncated += 1

    entity_validator = validators["entity"]
    shard_validator = validators["shard"]
    entity_count = 0
    for shard_name, shard_payload in documents.shards.items():
        for entity in shard_payload.get("entities", ()):
            entity_count += 1
            entity_id = entity.get("id") if isinstance(entity, dict) else None
            record(
                "entity",
                entity_id if isinstance(entity_id, str) else None,
                entity_validator.iter_errors(entity),
            )
        record(f"shard:{shard_name}", None, shard_validator.iter_errors(shard_payload))

    record("index", None, validators["index"].iter_errors(documents.index))
    record("obtain", None, validators["obtain"].iter_errors(documents.obtain))
    record("manifest", None, validators["manifest"].iter_errors(documents.manifest))

    checked = {
        "entity": entity_count,
        "shard": len(documents.shards),
        "index": 1,
        "obtain": 1,
        "manifest": 1,
    }
    return ConformanceReport(checked=checked, failures=tuple(failures), truncated_count=truncated)
