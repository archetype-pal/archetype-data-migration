from __future__ import annotations

from unicodedata import category

CAROUSEL_IMAGE_MAX_LENGTH = 100
CANONICAL_CAROUSEL_PREFIX = "carousel"

# Longest first so the legacy upload directory is consumed as one mapping,
# rather than being mistaken for a generic MEDIA_ROOT-relative path.
_SUPPORTED_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("media", "uploads", "carousel"),
    ("media", "carousel"),
    ("uploads", "carousel"),
    ("carousel",),
)


class CarouselImagePathError(ValueError):
    """A carousel image path cannot be mapped safely to the target schema."""


def carousel_image_path(
    image_file: str | None,
    image: str | None = None,
    *,
    carousel_id: int | None = None,
) -> str:
    """Return the canonical MEDIA_ROOT-relative path for a legacy carousel image.

    Legacy Models of Authority rows use ``/media/uploads/Carousel/...`` while
    the current Django ImageField stores ``carousel/...``. Already-normalized
    values and the older ``/media/carousel/...`` form are accepted so the
    transform is idempotent and safe across reviewed source variants.
    """

    candidates = [_clean_candidate(value) for value in (image_file, image)]
    candidates = [candidate for candidate in candidates if candidate is not None]
    context = f" for carousel id {carousel_id}" if carousel_id is not None else ""
    if not candidates:
        raise CarouselImagePathError(f"Carousel image path is empty{context}")

    normalized = [_normalize_candidate(candidate, context=context) for candidate in candidates]
    if len(set(normalized)) != 1:
        raise CarouselImagePathError(
            f"Conflicting carousel image paths{context}: image_file={image_file!r}, image={image!r}"
        )
    return normalized[0]


def _normalize_candidate(raw: str, *, context: str) -> str:
    if raw.startswith("//") or "\\" in raw or "://" in raw or "?" in raw or "#" in raw:
        raise CarouselImagePathError(f"Carousel image path is not a safe relative path{context}: {raw!r}")
    if any(category(character) == "Cc" for character in raw):
        raise CarouselImagePathError(f"Carousel image path contains a control character{context}: {raw!r}")

    path = raw[1:] if raw.startswith("/") else raw

    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise CarouselImagePathError(f"Carousel image path contains an unsafe segment{context}: {raw!r}")

    folded_parts = tuple(part.casefold() for part in parts)
    suffix: list[str] | None = None
    for prefix in _SUPPORTED_PREFIXES:
        if folded_parts[: len(prefix)] == prefix:
            suffix = parts[len(prefix) :]
            break

    if not suffix:
        supported = ", ".join("/".join(prefix) + "/..." for prefix in _SUPPORTED_PREFIXES)
        raise CarouselImagePathError(f"Unsupported carousel image path{context} {raw!r}; expected one of: {supported}")

    canonical = "/".join((CANONICAL_CAROUSEL_PREFIX, *suffix))
    if len(canonical) > CAROUSEL_IMAGE_MAX_LENGTH:
        raise CarouselImagePathError(
            f"Canonical carousel image path{context} exceeds {CAROUSEL_IMAGE_MAX_LENGTH} characters: {canonical!r}"
        )
    return canonical


def _clean_candidate(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text.strip():
        return None
    # Ordinary surrounding spaces are harmless source-data padding. Retain
    # every other character so the validator rejects tabs/newlines/control
    # characters instead of silently cleaning a dangerous path.
    return text.strip(" ")
