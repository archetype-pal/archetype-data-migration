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
- ``item_part_links``: how ``digipal_itempart`` rows become target ItemParts, which need exactly one
  historical item. Exact duplicate ``digipal_itempartitem`` rows are always collapsed.

      "item_part_links": {
        "unlinked_policy": "placeholder",           # fail (default) | placeholder
        "placeholder_historical_item": {"id": -1, "type": "Coin"},
        "multiple_links_policy": "first",           # fail (default) | first (lowest itempartitem id)
        "historical_item_by_item_part": {"1760": 2396}
      }

  With ``placeholder``, parts without any link (and the synthetic part for images without a part)
  belong to one placeholder historical item created with that id and legacy type label.
  ``historical_item_by_item_part`` picks the kept link for a part linked to several items.

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

_KNOWN_KEYS = frozenset(
    {"character_types", "repository_label_fallbacks", "item_image_path_overrides", "item_part_links"}
)
UNLINKED_ITEM_PART_POLICIES = ("fail", "placeholder")
MULTIPLE_ITEM_PART_LINK_POLICIES = ("fail", "first")


class SourceMappingError(ValueError):
    pass


@dataclass(frozen=True)
class ImagePathOverride:
    iipimage: str
    reason: str = ""


@dataclass(frozen=True)
class PlaceholderHistoricalItem:
    id: int
    type: str


@dataclass(frozen=True)
class ItemPartLinks:
    unlinked_policy: str = "fail"
    multiple_links_policy: str = "fail"
    placeholder_historical_item: PlaceholderHistoricalItem | None = None
    historical_item_by_item_part: Mapping[int, int] = field(default_factory=dict)

    @property
    def placeholder_id(self) -> int | None:
        if self.unlinked_policy == "placeholder" and self.placeholder_historical_item:
            return self.placeholder_historical_item.id
        return None

    def report(self) -> dict[str, Any]:
        placeholder = self.placeholder_historical_item
        return {
            "unlinked_policy": self.unlinked_policy,
            "multiple_links_policy": self.multiple_links_policy,
            "placeholder_historical_item": (
                {"id": placeholder.id, "type": placeholder.type} if placeholder is not None else None
            ),
            "historical_item_by_item_part": {str(k): v for k, v in sorted(self.historical_item_by_item_part.items())},
        }


@dataclass(frozen=True)
class SourceMapping:
    character_types: Mapping[str, str] = field(default_factory=lambda: dict(BUILTIN_CHARACTER_TYPES))
    repository_label_fallbacks: Mapping[int, str] = field(
        default_factory=lambda: dict(BUILTIN_REPOSITORY_LABEL_FALLBACKS_BY_ID)
    )
    item_image_path_overrides: Mapping[int, ImagePathOverride] = field(default_factory=dict)
    item_part_links: ItemPartLinks = field(default_factory=ItemPartLinks)
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
            "item_part_links": self.item_part_links.report(),
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


def _parse_item_part_links(raw: Any) -> ItemPartLinks:
    section = "item_part_links"
    if not isinstance(raw, dict):
        raise SourceMappingError(f"{section} must be a JSON object")
    unknown = sorted(
        key
        for key in raw
        if key
        not in {
            "unlinked_policy",
            "multiple_links_policy",
            "placeholder_historical_item",
            "historical_item_by_item_part",
        }
        and not str(key).startswith("_")
    )
    if unknown:
        raise SourceMappingError(f"Unknown {section} key(s): {', '.join(unknown)}")
    unlinked = raw.get("unlinked_policy", "fail")
    if unlinked not in UNLINKED_ITEM_PART_POLICIES:
        raise SourceMappingError(f"{section}.unlinked_policy must be one of {UNLINKED_ITEM_PART_POLICIES}")
    multiple = raw.get("multiple_links_policy", "fail")
    if multiple not in MULTIPLE_ITEM_PART_LINK_POLICIES:
        raise SourceMappingError(f"{section}.multiple_links_policy must be one of {MULTIPLE_ITEM_PART_LINK_POLICIES}")
    placeholder = None
    raw_placeholder = raw.get("placeholder_historical_item")
    if raw_placeholder is not None:
        if (
            not isinstance(raw_placeholder, dict)
            or not isinstance(raw_placeholder.get("id"), int)
            or not isinstance(raw_placeholder.get("type"), str)
            or not raw_placeholder["type"].strip()
        ):
            raise SourceMappingError(
                f"{section}.placeholder_historical_item needs an integer 'id' and a non-empty legacy 'type' label"
            )
        placeholder = PlaceholderHistoricalItem(raw_placeholder["id"], raw_placeholder["type"].strip())
    if unlinked == "placeholder" and placeholder is None:
        raise SourceMappingError(f"{section}.unlinked_policy 'placeholder' requires placeholder_historical_item")
    chosen = raw.get("historical_item_by_item_part", {})
    if not isinstance(chosen, dict) or not all(isinstance(v, int) for v in chosen.values()):
        raise SourceMappingError(f"{section}.historical_item_by_item_part must map part ids to historical item ids")
    return ItemPartLinks(
        unlinked_policy=unlinked,
        multiple_links_policy=multiple,
        placeholder_historical_item=placeholder,
        historical_item_by_item_part={_int_key(k, section): v for k, v in chosen.items()},
    )


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
    if "item_part_links" in data:
        kwargs["item_part_links"] = _parse_item_part_links(data["item_part_links"])
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
