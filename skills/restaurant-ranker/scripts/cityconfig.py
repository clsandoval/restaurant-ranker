"""cityconfig — per-city config loader for the restaurant ranker.

Usage
-----
from cityconfig import load_city, list_cities, UnknownCityError

load_city("manila")   # returns the parsed dict from cities/manila.json
load_city("Manila")   # case-insensitive; also works
list_cities()         # ["manila", ...] — all .json stems in cities/

Design
------
Cities are hand-authored JSON files under restaurant-ranker/cities/*.json.
Adding a new city is a config task (add a file), never a code change.  The
loader discovers cities by globbing *.json so no Python registry is needed.

The cities directory is resolved as:
    Path(__file__).resolve().parent.parent / "cities"
so the loader works from any caller CWD (not os.getcwd()).

Security (T-01-01)
------------------
City names are slugified to [a-z0-9-] before joining to the filesystem path.
Names containing '/', '..', '\\', or any character outside [a-z0-9-] are
rejected with ValueError so a caller cannot escape the cities/ directory
via path traversal.

Python 3.10 stdlib only — no third-party dependencies.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

__all__ = ["load_city", "list_cities", "UnknownCityError"]

# The cities directory sits one level up from this script file:
#   restaurant-ranker/scripts/cityconfig.py  ->  restaurant-ranker/cities/
_CITIES_DIR: Path = Path(__file__).resolve().parent.parent / "cities"

# Safe slug pattern: lowercase ASCII letters, digits, hyphens.
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


class UnknownCityError(Exception):
    """Raised when no config file exists for the requested city."""


def _slugify(name: str) -> str:
    """Normalise a city name to a safe filesystem slug.

    Rules:
    - Strip leading/trailing whitespace.
    - Lowercase.
    - Replace spaces with hyphens.
    - Reject anything containing '/', '\\', '..', or characters outside [a-z0-9-].

    Returns the slug or raises ValueError for unsafe names.
    """
    slug = name.strip().lower().replace(" ", "-")
    # Hard-reject path-separator characters before the regex check.
    if "/" in slug or "\\" in slug:
        raise ValueError(
            f"City name {name!r} contains path separators and cannot be used as a slug."
        )
    if not _SLUG_RE.match(slug):
        raise ValueError(
            f"City name {name!r} contains characters outside [a-z0-9-] "
            f"and cannot be safely used as a filename slug. "
            f"Provide a plain ASCII city name (e.g. 'manila', 'new-york')."
        )
    return slug


def load_city(name: str) -> dict:
    """Load and return the config dict for *name*.

    Parameters
    ----------
    name : str
        City name or slug (case-insensitive, leading/trailing whitespace stripped).
        Examples: "manila", "Manila", "new-york".

    Returns
    -------
    dict
        The parsed JSON config.  Guaranteed to contain at least:
        ``city``, ``slug``, ``country``, ``prestige_sources``,
        ``cuisine_taxonomy``, ``booking_platforms``.

    Raises
    ------
    UnknownCityError
        If no ``cities/<slug>.json`` file exists.  The message names the exact
        file path the caller must author and points at ``cities/_SCHEMA.md``.
    ValueError
        If *name* contains path-traversal characters (T-01-01).
    """
    slug = _slugify(name)
    city_file = _CITIES_DIR / f"{slug}.json"
    try:
        with city_file.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        schema_path = _CITIES_DIR / "_SCHEMA.md"
        raise UnknownCityError(
            f"No config found for city {name!r}. "
            f"To add it, create the file:\n"
            f"    cities/{slug}.json\n"
            f"See {schema_path} for the schema and a worked example."
        ) from None


def list_cities() -> list[str]:
    """Return the slugs of all configured cities.

    Discovers cities by globbing ``cities/*.json`` (excluding ``_SCHEMA.md``
    and any other non-city JSON files starting with ``_``).

    Returns
    -------
    list[str]
        Sorted list of slug strings (filename stems without ``.json``).
    """
    return sorted(
        p.stem for p in _CITIES_DIR.glob("*.json")
        if not p.stem.startswith("_")
    )
