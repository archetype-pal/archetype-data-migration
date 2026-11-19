"""Reviewed, per-source mapping decisions loaded from a JSON file.

The importer and the post-import audit were written against one DigiPal source. Other
DigiPal-framework sources use other vocabularies and need a few reviewed per-row decisions.
Those decisions live in a JSON *source mapping* file (one per source, kept with that source's
run manifest), never in code:

    {
      "character_types": {"lettre": "lettre", "ponctuation": "ponctuation"},
      "repository_label_fallbacks": {},
      "item_image_path_overrides": {
        "4": {"iipimage": "pim/jp2/x/0001.tif", "reason": "legacy row was tampered with"}
      }
    }

- ``character_types``: legacy ``digipal_ontographtype.name`` -> target ``Character.type``.
  Replaces the built-in reviewed list; legacy types not listed stay unsupported.
- ``repository_label_fallbacks``: legacy ``digipal_repository.id`` -> target label used when
  the legacy row has no usable short name. Replaces the built-in fallbacks (``{}`` disables them).
- ``item_image_path_overrides``: legacy ``digipal_image.id`` -> replacement legacy image path
  (a string, or an object with ``iipimage`` and an optional ``reason``). The path goes through
  the normal legacy path normalisation, as if it were the row's ``iipimage``.

A missing key keeps the built-in behaviour, so runs without a mapping file are unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
from typing import Any

SOURCE_MAPPING_ENV = "SOURCE_MAPPING_PATH"

BUILTIN_CHARACTER_TYPES: Mapping[str, str] = {
    value: value for value in ("letter", "abbreviation", "character-sequence", "punctuation", "accent")
}
BUILTIN_REPOSITORY_LABEL_FALLBACKS_BY_ID: Mapping[int, str] = {
    3: "CAM",
    8: "PMFED",
    11: "LTNA",
}

_KNOWN_KEYS = frozenset({"character_types", "repository_label_fallbacks", "item_image_path_overrides"})


class SourceMappingError(ValueError):
    pass


@dataclass(frozen=True)
class ImagePathOverride:
    iipimage: str
    reason: str = ""


@dataclass(frozen=True)
class SourceMapping:
    character_types: Mapping[str, str] = field(default_factory=lambda: dict(BUILTIN_CHARACTER_TYPES))
    repository_label_fallbacks: Mapping[int, str] = field(
        default_factory=lambda: dict(BUILTIN_REPOSITORY_LABEL_FALLBACKS_BY_ID)
    )
    item_image_path_overrides: Mapping[int, ImagePathOverride] = field(default_factory=dict)
    path: str | None = None
    sha256: str | None = None

    def character_type(self, legacy_type: Any) -> str | None:
        value = "" if legacy_type is None else str(legacy_type).strip()
        return self.character_types.get(value)

    def report(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "source": "file" if self.path else "built-in defaults",
            "character_types": dict(sorted(self.character_types.items())),
            "repository_label_fallbacks": {str(k): v for k, v in sorted(self.repository_label_fallbacks.items())},
            "item_image_path_overrides": {
                str(k): {"iipimage": v.iipimage, "reason": v.reason}
                for k, v in sorted(self.item_image_path_overrides.items())
            },
        }


DEFAULT_SOURCE_MAPPING = SourceMapping()


def _int_key(key: str, section: str) -> int:
    try:
        return int(key)
    except (TypeError, ValueError):
        raise SourceMappingError(f"{section}: key {key!r} must be a legacy integer id") from None


def _str_map(value: Any, section: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise SourceMappingError(f"{section} must be a JSON object")
    result: dict[str, str] = {}
    for key, target in value.items():
        if not isinstance(target, str) or not target.strip():
            raise SourceMappingError(f"{section}: value for {key!r} must be a non-empty string")
        result[str(key).strip()] = target.strip()
    return result


def parse_source_mapping(data: Any, *, path: str | None = None, sha256: str | None = None) -> SourceMapping:
    if not isinstance(data, dict):
        raise SourceMappingError("Source mapping must be a JSON object")
    unknown = sorted(key for key in data if key not in _KNOWN_KEYS and not str(key).startswith("_"))
    if unknown:
        raise SourceMappingError(f"Unknown source mapping key(s): {', '.join(unknown)}")

    kwargs: dict[str, Any] = {}
    if "character_types" in data:
        kwargs["character_types"] = _str_map(data["character_types"], "character_types")
    if "repository_label_fallbacks" in data:
        labels = _str_map(data["repository_label_fallbacks"], "repository_label_fallbacks")
        kwargs["repository_label_fallbacks"] = {
            _int_key(key, "repository_label_fallbacks"): label for key, label in labels.items()
        }
    if "item_image_path_overrides" in data:
        raw = data["item_image_path_overrides"]
        if not isinstance(raw, dict):
            raise SourceMappingError("item_image_path_overrides must be a JSON object")
        overrides: dict[int, ImagePathOverride] = {}
        for key, value in raw.items():
            image_id = _int_key(key, "item_image_path_overrides")
            if isinstance(value, str):
                value = {"iipimage": value}
            if not isinstance(value, dict) or not isinstance(value.get("iipimage"), str) or not value["iipimage"]:
                raise SourceMappingError(
                    f"item_image_path_overrides: {key!r} must be a path or an object with a non-empty 'iipimage'"
                )
            overrides[image_id] = ImagePathOverride(value["iipimage"].strip(), str(value.get("reason") or ""))
        kwargs["item_image_path_overrides"] = overrides
    return SourceMapping(path=path, sha256=sha256, **kwargs)


def load_source_mapping(path: Path | str | None = None) -> SourceMapping:
    """Load the mapping from ``path``, else from $SOURCE_MAPPING_PATH, else built-in defaults."""

    if path is None:
        path = os.environ.get(SOURCE_MAPPING_ENV) or None
    if path is None:
        return DEFAULT_SOURCE_MAPPING
    mapping_path = Path(path)
    try:
        raw = mapping_path.read_bytes()
    except OSError as exc:
        raise SourceMappingError(f"Could not read source mapping {mapping_path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceMappingError(f"Source mapping {mapping_path} is not valid JSON: {exc}") from exc
    return parse_source_mapping(data, path=str(mapping_path), sha256=hashlib.sha256(raw).hexdigest())
