# Emulator

A desktop simulator for **microcontroller circuits**, built to test a design —
schematic **and** firmware — *before* it's fabricated. You write a `circuit.json`
and a real Arduino `.ino`; the app runs the compiled firmware against a behavioral
+ analog model of the board, and a pre-production **ERC/analyzer** pass flags
wiring mistakes (floating pins, missing pull-ups, over-current, bus-speed limits,
shorts, address clashes…).

```
python3 run_gui.py examples/mpu6050/sketch.ino     # auto-loads circuit.json next to it
```

Built with Python 3.9 + PyQt6; sketches are compiled with `g++`. The code editor is
Monaco (QWebEngine); plots use pyqtgraph.

## How it works

### Two simulation domains
- **Electrical** — `core/bus.py` (`SimBus`) over `core/protocols/gpio.py` (`GPIOBus`):
  nets carry a voltage, resolved "lowest-wins" with pull-ups, plus `i2c`/`spi`/`uart`/
  `interrupt` protocol buses.
- **Real-world** — `core/rw_bus.py` (`RWBus`): scalar physical signals
  (light/heat/sound/ir/force) propagated with per-link loss; lives in the GUI canvas.

### Firmware (the real path)
Your `.ino` is compiled with the `firmware/sim_arduino.h` shim and run as a
subprocess. Every Arduino call (`digitalWrite`, `analogRead`, `ledcWrite`, `Wire.*`,
`attachInterrupt`, `Serial.*`) is bridged over stdin/stdout to `core/cpp_runtime.py`,
which drives the bus and replies. `delay()` advances simulated time. Supported:
GPIO, ADC, LEDC/PWM, **I2C (`Wire`)**, **external interrupts**, and Serial in/out.

### Fidelity tiers (`core/fidelity.py`)
A process-wide `CONFIG` selects **Basic** vs **Advanced** per domain, live, from the
**Simulation** menu:
- `real_world` — advanced LDR (spectral response, log-R, response lag), loss-node
  wavelength filter.
- `adc` — ESP32-like window + non-linearity + noise.
- `electrical` — **runtime MNA**: solve the real network each tick (see below).

### Runtime MNA (`physics/runtime_mna.py`)
In the Advanced `electrical` tier, the live sim solves the actual circuit each tick
with a SPICE-style MNA solver (`physics/mna/`): driven nets (rails, firmware GPIO,
sensor outputs, cap junctions) are pinned as sources, the R/diode/LED interconnect is
stamped, and internal nodes are solved — so a divider reads its true 1.65 V instead of
the behavioral approximation. *Opt-in (default Basic).* See [DESIGN.md](DESIGN.md).

### Power rails (`core/power.py`)
Rails are **not** ideal — each has a Thévenin source impedance (default 0.1 Ω;
override per rail with `"3V3": {"v": 3.3, "r_src": 0.5}`). Heavy/shorted loads sag
the rail (in the runtime MNA and in the analyzer's loaded-rail solve), and a VCC that
drops below a part's `v_min` is flagged as `erc.brownout`. Stable by default, never
infinitely perfect.

## Pre-production analyzer / ERC (`core/analyzer.py`)
A static "compile" pass (also runs on load/Run in the GUI → **Problems** panel)
identifies electrically-significant phenomena and flags faults:

| Check | Catches |
|---|---|
| `erc.floating` / `erc.unconnected` | floating required inputs (e.g. a dangling AD0) |
| `erc.power_window` / `erc.no_power` | VCC out of range / not on a rail |
| `erc.missing_pullup` | I2C/open-drain line with no pull-up |
| `erc.bus_speed` | rise-time (pull-up × bus C) exceeds the I2C mode limit |
| `erc.indeterminate_level` | a divider sets a digital input into the forbidden band (MNA) |
| `erc.gpio_overcurrent` | LED/load with no series resistor on a GPIO (MNA) |
| `erc.output_short` / `erc.gpio_short` | an output driven onto a power rail |
| `erc.contention` | multiple push-pull outputs on one net |
| `erc.i2c_collision` | two devices at the same I2C address |
| `erc.brownout` | rail sags below a part's V_min under load (source impedance) |

Results are also tolerance-cornered and **memoized** (`CharacterizationCache`,
on-disk `.sim_cache/`) so re-analysis of an unchanged board is free. Metadata lives in
each part's `descriptor.json` (`pin_contracts`, `tolerance`, `idd_ma`, GPIO drive
specs) — see `core/contracts.py`.

## Parts (22)
LEDs/IR LED/RGB LED, resistor/cap/inductor (passives), photoresistor, photodiode,
NTC, TMP36, FSR, microphone, hall, PIR, IR receiver, reed switch, button,
potentiometer, buzzer, relay, servo, DC motor, NPN transistor, **MPU-6050 IMU**,
ESP32-WROOM-32. Each is `parts/<name>/{model.py,descriptor.json}` and self-registers
via `core/registry.py`. Sensors expose `set_*` hooks driven live from GUI nodes
(sliders / the MPU's draggable 3D orientation cube).

## Examples
- `examples/pot_led_ldr` — pot → LED brightness → photoresistor feedback.
- `examples/mpu6050` — I2C IMU read-out (Wire), ERC-clean.
- `examples/mpu6050_interrupt` — interrupt-driven IMU (INT → GPIO ISR).
- `examples/button_led` — debounced button + LED.

## Tests
```
python3 tests/test_analyzer.py     # ERC + MNA islands + caching
python3 tests/test_firmware.py     # compiled Wire/I2C + interrupts (needs g++)
python3 tests/test_electrical.py   # runtime MNA divider
```

## Roadmap / known gaps
Larger items not yet built (tracked in [DESIGN.md](DESIGN.md)):
- **LED brightness under runtime MNA** — `LEDNode` should read the diode's solved
  current instead of its anode-voltage heuristic.
- **Firmware bridge breadth** — SPI, UART-to-peripheral, second I2C bus, `tone()`,
  multiple MCUs.
- **MPU depth** — AD0→address from the pin, FIFO, DMP, DLPF/sample-rate effects.
- **Real-world domains** — bridge heat/sound/ir/force (only light is wired today).
- **Schematic/net overlay view**, transient/AC on islands, brown-out (rail source
  impedance), and CI.

See [DESIGN.md](DESIGN.md) for the full architecture and phased plan.
