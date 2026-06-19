"""
KiCad 6/7 schematic parser (.kicad_sch).

Produces a NetList that maps every component pin to a named net.
Connectivity is resolved by coordinate matching:
  - Pin positions are calculated from lib_symbols offsets + symbol placement
  - Wire segments build a graph of connected coordinates (union-find)
  - Net labels and power symbols name the groups
  - Pin coordinates are matched into that graph to get their net name

Supports: wires, net labels, global labels, power symbols, junctions.
Does not support: buses, hierarchical sheets (treated as unconnected).
"""

from __future__ import annotations
import math
import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------- S-expr ------

def _tokenize(text: str) -> list[str]:
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in "()":
            tokens.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                if text[j] == '\\' and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            tokens.append("".join(buf))
            i = j + 1
        elif c in " \t\n\r":
            i += 1
        else:
            j = i
            while j < n and text[j] not in " \t\n\r()\"":
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


def _parse(tokens: list[str], pos: int = 0):
    """Return (tree, next_pos). Tree is a str atom or a list."""
    if tokens[pos] == "(":
        pos += 1
        items = []
        while tokens[pos] != ")":
            item, pos = _parse(tokens, pos)
            items.append(item)
        return items, pos + 1
    else:
        return tokens[pos], pos + 1


# --------------------------------------------------------------- helpers ------

def _find(node: list, key: str) -> list | None:
    for child in node:
        if isinstance(child, list) and child and child[0] == key:
            return child
    return None


def _find_all(node: list, key: str) -> list[list]:
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _snap(x, y) -> tuple[float, float]:
    """Round to 4 dp to absorb floating-point drift between wire/pin coords."""
    return (round(_f(x), 4), round(_f(y), 4))


def _kicad_rotate(px: float, py: float, angle_deg: float) -> tuple[float, float]:
    """
    Rotate point (px, py) by angle_deg in KiCad's coordinate system.
    KiCad uses CCW angles in a Y-down frame, equivalent to CW in standard math.
    Transform: x' = px·cos(R) + py·sin(R)
               y' = -px·sin(R) + py·cos(R)
    """
    r = math.radians(angle_deg)
    c, s = math.cos(r), math.sin(r)
    return (px * c + py * s, -px * s + py * c)


# --------------------------------------------------------------- data --------

@dataclass
class PinConnection:
    reference: str
    pin_number: str
    pin_name: str
    net: str


@dataclass
class NetList:
    # net_name → [PinConnection, ...]
    nets: dict[str, list[PinConnection]] = field(default_factory=dict)
    # reference → {"value": str, "part": str, "pins": {pin_number: net_name}}
    components: dict[str, dict] = field(default_factory=dict)

    def pins_on_net(self, net_name: str) -> list[PinConnection]:
        return self.nets.get(net_name, [])

    def nets_for_ref(self, reference: str) -> dict[str, str]:
        return self.components.get(reference, {}).get("pins", {})

    def find_net_for_pin(self, reference: str, pin_number: str) -> str | None:
        return self.nets_for_ref(reference).get(pin_number)

    def find_cs_net(self, reference: str) -> str | None:
        """Return the net name of the CS/SS pin for SPI devices."""
        pins = self.nets_for_ref(reference)
        for name, net in pins.items():
            if name.upper() in ("CS", "SS", "NSS", "CE", "TCS", "T_CS"):
                return net
        return None


# ------------------------------------------------------------- union-find ----

class _UF:
    def __init__(self):
        self._p: dict = {}

    def add(self, x):
        if x not in self._p:
            self._p[x] = x

    def find(self, x) -> object:
        self._p.setdefault(x, x)
        root = x
        while self._p[root] != root:
            root = self._p[root]
        while self._p[x] != root:
            self._p[x], x = root, self._p[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._p[ra] = rb


# -------------------------------------------------------------- parser -------

def parse(path: str | Path) -> NetList:
    """Parse a KiCad 6/7 .kicad_sch file and return a NetList."""
    text = Path(path).read_text(encoding="utf-8")
    tokens = _tokenize(text)
    tree, _ = _parse(tokens)
    return _build(tree)


def _build(tree: list) -> NetList:
    nl = NetList()
    uf = _UF()

    # 1. Collect pin offsets from lib_symbols
    lib_pins: dict[str, dict[str, tuple[float, float]]] = {}
    lib_sym_node = _find(tree, "lib_symbols")
    if lib_sym_node:
        for sym in _find_all(lib_sym_node, "symbol"):
            name = sym[1] if len(sym) > 1 and isinstance(sym[1], str) else ""
            lib_pins[name] = _extract_lib_pins(sym)

    # 2. Build coordinate graph from wires and junctions
    label_at: dict[tuple, str] = {}   # coord → net name

    for node in tree:
        if not isinstance(node, list) or not node:
            continue
        tag = node[0]

        if tag == "wire":
            pts = _find(node, "pts")
            if pts:
                xys = _find_all(pts, "xy")
                if len(xys) >= 2:
                    p0 = _snap(xys[0][1], xys[0][2])
                    p1 = _snap(xys[1][1], xys[1][2])
                    uf.add(p0); uf.add(p1)
                    uf.union(p0, p1)

        elif tag == "junction":
            at = _find(node, "at")
            if at and len(at) >= 3:
                p = _snap(at[1], at[2])
                uf.add(p)

        elif tag in ("label", "net_label"):
            at = _find(node, "at")
            name = node[1] if len(node) > 1 and isinstance(node[1], str) else ""
            if at and len(at) >= 3 and name:
                p = _snap(at[1], at[2])
                uf.add(p)
                label_at[p] = name

        elif tag == "global_label":
            at = _find(node, "at")
            name = node[1] if len(node) > 1 and isinstance(node[1], str) else ""
            if at and len(at) >= 3 and name:
                p = _snap(at[1], at[2])
                uf.add(p)
                label_at[p] = name    # global labels share names across sheets

    # 3. Assign net names to union groups
    group_net: dict[object, str] = {}
    for pt, net_name in label_at.items():
        root = uf.find(pt)
        group_net[root] = net_name

    def _net_at(pt: tuple) -> str:
        uf.add(pt)
        root = uf.find(pt)
        if root in group_net:
            return group_net[root]
        # Synthetic name from root coordinate (no label on this net)
        rx, ry = root
        return f"Net_{int(rx*100):+d}_{int(ry*100):+d}"

    # 4. Process power symbols — their value IS their net name
    for node in tree:
        if not isinstance(node, list) or not node or node[0] != "symbol":
            continue
        lib_id_n = _find(node, "lib_id")
        if not lib_id_n:
            continue
        lib_id: str = lib_id_n[1]
        if not lib_id.startswith("power:"):
            continue

        val = _prop(node, "Value")
        at_n = _find(node, "at")
        if not (val and at_n and len(at_n) >= 3):
            continue

        sx, sy = _f(at_n[1]), _f(at_n[2])
        sr = _f(at_n[3]) if len(at_n) > 3 else 0.0
        for pin_num, (ox, oy) in lib_pins.get(lib_id, {}).items():
            rx, ry = _kicad_rotate(ox, oy, sr)
            pt = _snap(sx + rx, sy + ry)
            uf.add(pt)
            root = uf.find(pt)
            group_net[root] = val

    # 5. Process symbol instances
    for node in tree:
        if not isinstance(node, list) or not node or node[0] != "symbol":
            continue
        lib_id_n = _find(node, "lib_id")
        if not lib_id_n:
            continue
        lib_id = lib_id_n[1]
        if lib_id.startswith("power:"):
            continue

        ref = _prop(node, "Reference")
        val = _prop(node, "Value")
        if not ref or ref.startswith("#"):
            continue

        at_n = _find(node, "at")
        if not at_n or len(at_n) < 3:
            continue
        sx, sy = _f(at_n[1]), _f(at_n[2])
        sr = _f(at_n[3]) if len(at_n) > 3 else 0.0

        mirror_n = _find(node, "mirror")
        mx = isinstance(mirror_n, list) and "x" in mirror_n
        my = isinstance(mirror_n, list) and "y" in mirror_n

        pin_defs = lib_pins.get(lib_id, {})
        comp_pins: dict[str, str] = {}

        for pin_num, (ox, oy) in pin_defs.items():
            px = -ox if my else ox
            py = -oy if mx else oy
            rx, ry = _kicad_rotate(px, py, sr)
            pt = _snap(sx + rx, sy + ry)
            net_name = _net_at(pt)
            comp_pins[pin_num] = net_name

        nl.components[ref] = {"value": val or "", "part": lib_id, "pins": comp_pins}

        for pin_num, net_name in comp_pins.items():
            nl.nets.setdefault(net_name, []).append(
                PinConnection(reference=ref, pin_number=pin_num,
                              pin_name=pin_num, net=net_name)
            )

    return nl


def _prop(node: list, key: str) -> str | None:
    """Extract value of a (property "Key" "Value" ...) child."""
    for child in _find_all(node, "property"):
        if len(child) > 2 and child[1] == key:
            return child[2]
    return None


def _extract_lib_pins(sym_node: list) -> dict[str, tuple[float, float]]:
    """Recursively collect {pin_number: (offset_x, offset_y)} from a lib symbol."""
    pins: dict[str, tuple[float, float]] = {}
    for child in sym_node:
        if not isinstance(child, list) or not child:
            continue
        if child[0] == "pin":
            at = _find(child, "at")
            num_n = _find(child, "number")
            if at and num_n and len(at) >= 3 and len(num_n) > 1:
                pins[num_n[1]] = (_f(at[1]), _f(at[2]))
        elif child[0] == "symbol":
            pins.update(_extract_lib_pins(child))
    return pins
