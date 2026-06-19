"""
Component registry — maps KiCad reference prefixes and lib_ids to
simulation categories and Node subclasses.

Adding a new part:
  1. Create parts/<name>/model.py with a Node subclass.
  2. Call registry.register_part("Device:MyPart", MyPartNode)
     or add it to KNOWN_PARTS below if it ships with the simulator.

The registry is intentionally flat — no inheritance hierarchy, just a
lookup table. Parts register themselves; core never imports parts directly.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.node import Node


# -------------------------------------------------------- component category --

class Category(Enum):
    RESISTOR    = auto()   # R  — handled by PassiveModel
    CAPACITOR   = auto()   # C  — handled by PassiveModel
    INDUCTOR    = auto()   # L  — handled by PassiveModel
    FERRITE     = auto()   # FB — inductor + DCR, handled by PassiveModel
    DIODE       = auto()   # D  — future passive (voltage drop)
    TRANSISTOR  = auto()   # Q  — future active
    IC          = auto()   # U  — needs a Node subclass
    CONNECTOR   = auto()   # J  — passthrough, no physics
    CRYSTAL     = auto()   # Y  — clock source stub
    SWITCH      = auto()   # SW — digital on/off
    BATTERY     = auto()   # BT — constant voltage source
    TEST_POINT  = auto()   # TP — probe point, no physics
    UNKNOWN     = auto()


# ------------------------------------------------- reference prefix → category

PREFIX_CATEGORY: dict[str, Category] = {
    "R":  Category.RESISTOR,
    "C":  Category.CAPACITOR,
    "L":  Category.INDUCTOR,
    "FB": Category.FERRITE,
    "D":  Category.DIODE,
    "LED":Category.DIODE,
    "Q":  Category.TRANSISTOR,
    "U":  Category.IC,
    "IC": Category.IC,
    "J":  Category.CONNECTOR,
    "P":  Category.CONNECTOR,
    "Y":  Category.CRYSTAL,
    "X":  Category.CRYSTAL,
    "SW": Category.SWITCH,
    "S":  Category.SWITCH,
    "BT": Category.BATTERY,
    "TP": Category.TEST_POINT,
}

# Categories that are handled purely by PassiveModel (no Node subclass needed)
PASSIVE_CATEGORIES = {
    Category.RESISTOR,
    Category.CAPACITOR,
    Category.INDUCTOR,
    Category.FERRITE,
}

# Categories that need no simulation model at all
INERT_CATEGORIES = {
    Category.CONNECTOR,
    Category.TEST_POINT,
}


def category_of(reference: str) -> Category:
    """Derive category from a reference designator like 'R1', 'U3', 'FB2'."""
    # Strip trailing digits to get the prefix
    prefix = reference.rstrip("0123456789").upper()
    # Try longest match first (e.g. "LED" before "L")
    for length in (3, 2, 1):
        if prefix[:length] in PREFIX_CATEGORY:
            return PREFIX_CATEGORY[prefix[:length]]
    return Category.UNKNOWN


# ----------------------------------------------- lib_id → Node class lookup --

@dataclass
class PartEntry:
    lib_id: str
    node_class: type          # Node subclass to instantiate
    i2c_address: int | None = None    # default 7-bit I2C address, if applicable
    spi_cs_pin_name: str = "CS"       # pin name used as SPI chip-select
    notes: str = ""


class Registry:
    def __init__(self):
        self._parts: dict[str, PartEntry] = {}     # lib_id → PartEntry
        self._fallback: dict[Category, type] = {}  # category → generic Node class

    # ---------------------------------------------------------------- register

    def register_part(self, lib_id: str, node_class: type,
                       i2c_address: int | None = None,
                       spi_cs_pin_name: str = "CS",
                       notes: str = ""):
        """Register a specific part by its KiCad lib_id."""
        self._parts[lib_id] = PartEntry(
            lib_id=lib_id,
            node_class=node_class,
            i2c_address=i2c_address,
            spi_cs_pin_name=spi_cs_pin_name,
            notes=notes,
        )

    def register_fallback(self, category: Category, node_class: type):
        """Register a generic Node class for an entire category."""
        self._fallback[category] = node_class

    # ----------------------------------------------------------------- lookup

    def get_entry(self, lib_id: str) -> PartEntry | None:
        return self._parts.get(lib_id)

    def resolve(self, reference: str, lib_id: str) -> type | None:
        """
        Return the Node class for this component, or None if it is a
        passive / inert component that needs no Node subclass.
        """
        cat = category_of(reference)

        if cat in PASSIVE_CATEGORIES or cat in INERT_CATEGORIES:
            return None

        # Exact lib_id match first
        entry = self._parts.get(lib_id)
        if entry:
            return entry.node_class

        # Fall back to category default
        return self._fallback.get(cat)

    def i2c_address(self, lib_id: str) -> int | None:
        entry = self._parts.get(lib_id)
        return entry.i2c_address if entry else None

    def spi_cs_pin(self, lib_id: str) -> str:
        entry = self._parts.get(lib_id)
        return entry.spi_cs_pin_name if entry else "CS"

    def known_lib_ids(self) -> list[str]:
        return list(self._parts.keys())


# --------------------------------------------------- module-level singleton --

_registry = Registry()


def register_part(lib_id: str, node_class: type, **kwargs):
    _registry.register_part(lib_id, node_class, **kwargs)


def register_fallback(category: Category, node_class: type):
    _registry.register_fallback(category, node_class)


def resolve(reference: str, lib_id: str) -> type | None:
    return _registry.resolve(reference, lib_id)


def get_entry(lib_id: str) -> PartEntry | None:
    return _registry.get_entry(lib_id)


def i2c_address(lib_id: str) -> int | None:
    return _registry.i2c_address(lib_id)
