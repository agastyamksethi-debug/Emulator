"""
circuit.py — Hand-written circuit definition loader.

Instead of drawing a KiCad schematic, write a circuit.json file that lists
every part, its values, and which pins connect to which named nets.
The simulator reads this, instantiates all parts, wires the bus, and derives
the firmware pin-map automatically from the MCU's gpio_map.

Circuit JSON format
-------------------
{
  "mcu": "U1",              ← which part is the MCU (auto-detected if omitted)

  "power": {                ← nets driven to a fixed voltage (power rails)
    "3V3": 3.3,
    "GND": 0.0
  },

  "parts": {
    "U1": {
      "type": "esp32-wroom-32",
      "pins": {             ← pin_name → net_name  (only pins you've wired)
        "VDD":  "3V3",
        "GND_1":"GND",
        "IO2":  "GPIO_2"
      }
    },
    "R1": {
      "type": "resistor",
      "value": "220",       ← ohms; use SI suffix: "10k", "4.7k", "1M"
      "pins": { "1": "GPIO_2", "2": "LED_A" }
    },
    "D1": {
      "type": "led",
      "vf": 2.0,
      "color": "red",
      "pins": { "A": "LED_A", "K": "GND" }
    },
    "C1": {
      "type": "capacitor",
      "value": "100n",      ← farads with suffix: "100n", "10u", "1p"
      "pins": { "+": "3V3", "-": "GND" }
    }
  }
}
"""

from __future__ import annotations
import json
import os

from core.netlist import NetList, PinConnection

_PARTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "parts")
)

# Simple type name → KiCad lib_id used by the registry
_TYPE_TO_LIB_ID: dict[str, str] = {
    "resistor":        "Device:R",
    "capacitor":       "Device:C",
    "inductor":        "Device:L",
    "ferrite":         "Device:FB",
    "led":             "Device:LED",
    "esp32-wroom-32":  "ESP32-WROOM-32:ESP32-WROOM-32",
}


# ── loading ──────────────────────────────────────────────────────────────────

def load(path: str) -> dict:
    """Parse a circuit.json file and return the raw dict."""
    with open(path) as f:
        return json.load(f)


# ── conversion to NetList ─────────────────────────────────────────────────────

def to_netlist(circuit: dict) -> NetList:
    """
    Convert a circuit dict to a NetList so the simulation engine (physics,
    registry auto-instantiation) can consume it without modification.
    """
    nl = NetList()

    for ref, part_def in circuit.get("parts", {}).items():
        part_type = part_def.get("type", "")
        lib_id    = _TYPE_TO_LIB_ID.get(part_type, part_type)
        pins      = {k: v for k, v in part_def.get("pins", {}).items() if v}

        # Build the component entry in the same shape _auto_instantiate() expects
        comp: dict = {
            "value": str(part_def.get("value", "")),
            "part":  lib_id,
            "pins":  pins,
        }
        # Pass through extra descriptor overrides (vf, color, etc.)
        for k, v in part_def.items():
            if k not in ("type", "pins", "value"):
                comp[k] = v

        nl.components[ref] = comp

        # Populate the nets index
        for pin_name, net_name in pins.items():
            nl.nets.setdefault(net_name, []).append(
                PinConnection(
                    reference=ref,
                    pin_number=pin_name,
                    pin_name=pin_name,
                    net=net_name,
                )
            )

    return nl


# ── MCU detection and pin-map derivation ─────────────────────────────────────

def find_mcu(circuit: dict) -> str | None:
    """
    Return the reference of the MCU part.
    Uses circuit["mcu"] if present, otherwise finds the first part whose
    descriptor.json contains a gpio_map.
    """
    if "mcu" in circuit:
        return circuit["mcu"]

    for ref, part_def in circuit.get("parts", {}).items():
        part_type = part_def.get("type", "")
        desc_path = os.path.join(_PARTS_DIR, part_type, "descriptor.json")
        if not os.path.exists(desc_path):
            continue
        with open(desc_path) as f:
            desc = json.load(f)
        if desc.get("gpio_map"):
            return ref

    return None


def mcu_pinmap(circuit: dict, mcu_ref: str) -> dict[int, str]:
    """
    Build {arduino_gpio_number: bus_net_name} for the named MCU part.

    Works by cross-referencing the MCU's gpio_map (descriptor.json) with the
    pin→net wiring declared in the circuit file:
      gpio_map["2"]  = "IO2"         (GPIO 2 is on physical pin IO2)
      circuit pins["IO2"] = "GPIO_2" (IO2 is wired to net GPIO_2)
      → pin_map[2] = "GPIO_2"
    """
    part_def  = circuit.get("parts", {}).get(mcu_ref, {})
    part_type = part_def.get("type", "")
    desc_path = os.path.join(_PARTS_DIR, part_type, "descriptor.json")

    if not os.path.exists(desc_path):
        return {}

    with open(desc_path) as f:
        desc = json.load(f)

    gpio_map     = desc.get("gpio_map", {})      # {"2": "IO2", "36": "IO36", …}
    circuit_pins = part_def.get("pins", {})       # {"IO2": "GPIO_2", "VDD": "3V3", …}

    pin_map: dict[int, str] = {}
    for gpio_num_s, pin_name in gpio_map.items():
        net = circuit_pins.get(pin_name)
        if net:
            pin_map[int(gpio_num_s)] = net

    return pin_map
