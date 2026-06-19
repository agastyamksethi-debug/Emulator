# PCB Simulator — Part Authoring Guide

This document is the complete specification for creating a new part for the simulator.
It is written for both human developers and AI models. Follow it exactly — the simulator
core will not work correctly with parts that deviate from this contract.

---

## Table of Contents

1. [Part Classifications](#1-part-classifications)
2. [Directory Structure](#2-directory-structure)
3. [descriptor.json — Full Schema](#3-descriptorjson--full-schema)
4. [Node Subclass Requirements by Type](#4-node-subclass-requirements-by-type)
5. [Extracting Data from Datasheets](#5-extracting-data-from-datasheets)
6. [Registering a Part](#6-registering-a-part)
7. [Naming Conventions](#7-naming-conventions)
8. [Worked Examples](#8-worked-examples)

---

## 1. Part Classifications

Every part falls into exactly one primary classification. This determines which
base interface it must implement and how the simulator instantiates it.

### 1.1 MCU (Microcontroller)
**Reference prefix:** `U`
**KiCad lib_id examples:** `MCU_Espressif:ESP32-WROOM-32`, `MCU_Microchip_AVR:ATmega328P`

The MCU is the only part that *runs firmware*. It owns an `ArduinoShim` instance
and a `PinMap`. Its `tick()` does not need to advance firmware — firmware runs via
the shim when called by the runner. The MCU node's job is to:
- Hold the GPIO pin-to-net mapping for its instance
- Validate every firmware API call against its pin capabilities
- Drive net voltages on its output pins via the shim

MCU parts are the most complex to author. They require a complete `gpio_map` and
`pin_caps` table in the descriptor.

### 1.2 Sensor (I2C or SPI)
**Reference prefix:** `U`
**Examples:** MPU6050, ADS1115, BMP280, BME688, MAX31855

A sensor responds to I2C or SPI transactions from the MCU firmware. It has an
internal register map that the firmware reads and writes. The simulation model
stores either:
- **Injected values** — test code sets `node.inject(accel_x=1.2)` to fake sensor data
- **Computed values** — the model calculates output from physics state (e.g. temperature
  from the thermal model feeds a temperature sensor)

Sensors never initiate communication. They only respond.

### 1.3 Display / Output IC
**Reference prefix:** `U`
**Examples:** ST7789, SSD1306, WS2812 (NeoPixel), TM1637

Receives data from the MCU and produces a visible output. The simulation model
maintains a framebuffer or output state that the test harness or UI can read.
The model must not depend on pygame or any UI library — rendering is the
consumer's job. The model just holds the state.

### 1.4 Interface IC
**Reference prefix:** `U`
**Examples:** XPT2046 (touch), MCP2515 (CAN), W5500 (Ethernet), CH340 (USB-UART)

Bridges two protocols or provides a specific interface. Models the protocol
conversion behaviour and any buffering. The XPT2046 for example receives SPI
commands and returns ADC values for touch coordinates.

### 1.5 Power IC
**Reference prefix:** `U`
**Examples:** AMS1117 (LDO), TPS63020 (buck-boost), INA219 (current sense)

Regulates or monitors power rails. In the simulator, power ICs are modelled
lightly — they drive their output net to a constant voltage (derived from
input voltage and their regulation ratio). They do not need full switching
simulation. Current-sense ICs (INA219) are full sensor models.

### 1.6 Passive
**Reference prefixes:** `R`, `C`, `L`, `FB`

Handled entirely by `physics/passive.py`. **You do not write a Node subclass for
passives.** The `PassiveModel` auto-instantiates them from the netlist using the
reference designator and value string. You only need to add entries to the part
registry if you want a non-standard value parser or thermal data.

Ferrite beads (`FB`) are modelled as inductors with DCR. At DC they are
resistors; the full RL model handles transition.

### 1.7 Discrete Semiconductor
**Reference prefixes:** `D`, `LED`, `Q`

- **Diode / LED:** two-terminal, non-linear. Model as a voltage-threshold device
  (Vf = 0.7 V for silicon, 2.0–3.5 V for LED depending on colour). Above threshold,
  net voltage is clamped. Below, it is open.
- **Transistor (BJT/FET):** three-terminal switch or amplifier. Model as a
  voltage-controlled switch: if Vbe > 0.7 V (BJT) or Vgs > Vth (FET), collector/drain
  is pulled toward emitter/source.

These require a `Node` subclass but are simpler than ICs.

### 1.8 Connector
**Reference prefix:** `J`

No simulation model needed. Connectors are inert — they just pass signals through.
Do not create a Node subclass. The bus treats connector pins as net aliases.

### 1.9 Crystal / Oscillator
**Reference prefix:** `Y`, `X`

No simulation model needed. Crystals drive a clock net at their nominal frequency.
The simulator does not model clock domains — they are treated as always-running.

---

## 2. Directory Structure

Every part lives in its own subdirectory under `parts/`:

```
parts/
  <part_name>/
    descriptor.json       ← REQUIRED for all parts
    model.py              ← REQUIRED for all except passives and connectors
    arduino/              ← REQUIRED for MCU parts only
      <LibName>.h         ← Arduino-compatible C++ header (same API as shim)
      library.properties
      keywords.txt
      examples/
        <ExampleName>/
          <ExampleName>.ino
```

**Part name convention:** lowercase, hyphens for spaces. Use the IC part number.
```
parts/
  mpu6050/
  ads1115/
  esp32-wroom-32/
  st7789/
  xpt2046/
  ina219/
```

---

## 3. descriptor.json — Full Schema

Every field is documented below. Fields marked **REQUIRED** must be present.
Fields marked *optional* may be omitted; defaults are shown.

```jsonc
{
  // ── Identity ─────────────────────────────────────────────────────────────

  "part": "MPU-6050",           // REQUIRED. Exact manufacturer part number.
  "manufacturer": "TDK InvenSense",  // REQUIRED.
  "description": "6-axis IMU, 3-axis gyro + 3-axis accelerometer, I2C",
                                // REQUIRED. One line, include protocol.
  "classification": "sensor",   // REQUIRED. One of:
                                //   mcu | sensor | display | interface |
                                //   power_ic | discrete | passive |
                                //   connector | crystal
  "protocol": "I2C",            // REQUIRED. One of: I2C | SPI | UART |
                                //   GPIO | SPI+GPIO | I2C+GPIO | none
  "datasheet": "https://...",   // URL or filename in parts/<name>/

  // ── Package / Visual ─────────────────────────────────────────────────────

  "package": "QFN-24",          // REQUIRED. JEDEC package name.
  "visual": {                   // optional. Used by UI renderers.
    "width_mm": 4.0,
    "height_mm": 4.0,
    "color": "#2a2a2a"
  },

  // ── Electrical ───────────────────────────────────────────────────────────

  "vdd_min": 2.375,             // REQUIRED. Minimum supply voltage (V).
  "vdd_max": 3.46,              // REQUIRED. Maximum supply voltage (V).
  "vdd_nom": 3.3,               // optional. Nominal operating voltage (V).
  "idd_ua": 3900,               // optional. Typical supply current (µA).

  // ── Pins ─────────────────────────────────────────────────────────────────
  //
  // Map every pin name to its role. Pin names must match the KiCad symbol
  // exactly (check the .kicad_sym file or the symbol in your schematic).
  //
  // Pin types:
  //   power        — VDD, VCC, VDDIO etc.
  //   ground       — GND, VSS, AGND etc.
  //   i2c_sda      — I2C data
  //   i2c_scl      — I2C clock
  //   spi_cs       — SPI chip select (active low)
  //   spi_clk      — SPI clock
  //   spi_mosi     — SPI MOSI (SDI, DIN, SDA in write-only SPI)
  //   spi_miso     — SPI MISO (SDO, DOUT)
  //   gpio         — general purpose digital I/O
  //   gpio_out     — digital output only
  //   gpio_in      — digital input only
  //   adc_in       — analog input
  //   interrupt    — interrupt output (active low unless noted)
  //   reset        — hardware reset (active low unless noted)
  //   nc           — no connect
  //   address      — I2C address select pin (tied HIGH or LOW)

  "pins": {
    "VDD":   { "type": "power",   "voltage": 3.3 },
    "GND":   { "type": "ground" },
    "SDA":   { "type": "i2c_sda" },
    "SCL":   { "type": "i2c_scl" },
    "AD0":   { "type": "address", "note": "LOW=0x68, HIGH=0x69" },
    "INT":   { "type": "interrupt", "active": "low" },
    "FSYNC": { "type": "gpio_in",  "note": "Frame sync; tie to GND if unused" },
    "CPUM":  { "type": "nc" }
  },

  // ── I2C Configuration ─────────────────────────────────────────────────────
  // Include this block for all I2C devices.

  "i2c": {
    "address_default": "0x68",   // REQUIRED for I2C. 7-bit, as hex string.
    "address_alt": "0x69",       // optional. Alternate address when AD0=HIGH.
    "address_pin": "AD0",        // optional. Which pin selects the address.
    "speed_max_khz": 400         // optional. Max I2C clock (100 or 400 typical).
  },

  // ── SPI Configuration ─────────────────────────────────────────────────────
  // Include this block for all SPI devices.

  "spi": {
    "mode": 0,                   // REQUIRED for SPI. Clock polarity/phase (0–3).
    "max_speed_hz": 1000000,     // REQUIRED for SPI. Max clock frequency.
    "cs_pin": "CS",              // REQUIRED for SPI. Name of CS pin (from pins{}).
    "cs_active": "low",          // optional. Default "low".
    "word_size": 8               // optional. Default 8 bits.
  },

  // ── Register Map ──────────────────────────────────────────────────────────
  // Document every register the simulation model uses. Not every register
  // in the datasheet — only those your model.py reads or writes.
  // This section is documentation; the model.py is the implementation.

  "registers": {
    "0x6B": {
      "name": "PWR_MGMT_1",
      "reset_value": "0x40",
      "fields": {
        "SLEEP":    { "bit": 6, "note": "1=sleep, 0=active" },
        "CLKSEL":   { "bits": "2:0", "note": "0=internal 8MHz osc" }
      }
    },
    "0x3B": { "name": "ACCEL_XOUT_H", "note": "High byte of X acceleration" },
    "0x3C": { "name": "ACCEL_XOUT_L" },
    "0x43": { "name": "GYRO_XOUT_H",  "note": "High byte of X gyro rate" }
  },

  // ── MCU-Specific Fields ───────────────────────────────────────────────────
  // REQUIRED for classification=mcu only. Omit for all other parts.

  "gpio_map": {
    // Maps logical GPIO number (as string) to KiCad pin name.
    // Get KiCad pin names from the symbol in your .kicad_sch file.
    "0":  "IO0",
    "1":  "TXD0",
    "2":  "IO2",
    "3":  "RXD0",
    "4":  "IO4",
    "5":  "IO5",
    "12": "IO12",
    "13": "IO13",
    "14": "IO14",
    "15": "IO15",
    "16": "IO16",
    "17": "IO17",
    "18": "IO18",
    "19": "IO19",
    "21": "IO21",
    "22": "IO22",
    "23": "IO23",
    "25": "IO25",
    "26": "IO26",
    "27": "IO27",
    "32": "IO32",
    "33": "IO33",
    "34": "IO34",
    "35": "IO35",
    "36": "IO36",
    "39": "IO39"
  },

  "pin_caps": {
    // Maps GPIO number (as string) to list of capability strings.
    // Valid strings: digital_in, digital_out, adc, dac, pwm, spi, i2c,
    //                uart, input_only
    // input_only pins CANNOT be used as outputs — the shim enforces this.
    "0":  ["digital_in", "digital_out", "pwm"],
    "2":  ["digital_in", "digital_out", "pwm", "adc"],
    "25": ["digital_in", "digital_out", "dac", "pwm"],
    "34": ["digital_in", "adc", "input_only"],
    "35": ["digital_in", "adc", "input_only"],
    "36": ["digital_in", "adc", "input_only"],
    "39": ["digital_in", "adc", "input_only"]
  },

  // ── Thermal ───────────────────────────────────────────────────────────────
  // Used by physics/thermal.py. Get these from the datasheet thermal section.

  "thermal_resistance_c_per_w": 40.0,   // θJA — junction to ambient (°C/W)
  "thermal_capacitance_j_per_c": 1.0,   // thermal mass (J/°C). Estimate if
                                         // not in datasheet: 0.1 for small ICs,
                                         // 1.0 for QFP/QFN, 5.0 for TO-220.

  // ── Simulation Model ──────────────────────────────────────────────────────

  "simulation_model": "parts.mpu6050.model.MPU6050Node",
                                // REQUIRED (except passives/connectors).
                                // Python import path to the Node subclass.

  // ── Arduino Library ───────────────────────────────────────────────────────
  // REQUIRED for MCU parts only.

  "arduino_library": "parts/esp32-wroom-32/arduino"
}
```

---

## 4. Node Subclass Requirements by Type

### 4.1 All parts — base requirements

```python
from core.node import Node

class MyPartNode(Node):
    PART_ID = "my-part"   # matches the parts/ directory name

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        # Initialise your internal state here
        # DO NOT open files, start threads, or import pygame here

    def reset(self):
        # Restore to power-on state
        # Called by SimRunner.reset() and on hardware reset signal
        pass

    def tick(self, dt_ms: float):
        # Advance any time-dependent internal state
        # Keep this fast — it runs every simulation step
        # Do NOT read/write the bus here; that happens via protocol methods
        pass
```

### 4.2 I2C sensor

```python
class MPU6050Node(Node):
    I2C_ADDRESS_DEFAULT = 0x68

    def __init__(self, instance_id, descriptor):
        super().__init__(instance_id, descriptor)
        # I2C address: check AD0 pin net voltage after netlist loads
        self.i2c_address = self.I2C_ADDRESS_DEFAULT
        self._regs = bytearray(128)         # register file
        self._regs[0x6B] = 0x40            # PWR_MGMT_1 reset value: SLEEP=1
        self._regs[0x75] = 0x68            # WHO_AM_I

        # Injectable sensor values — set from test code
        self.accel = [0.0, 0.0, 1.0]      # x, y, z in g (1g default Z)
        self.gyro  = [0.0, 0.0, 0.0]      # x, y, z in deg/s
        self.temperature_c = 25.0

    def inject(self, **kwargs):
        # Test code calls: node.inject(accel_x=0.5, gyro_z=90.0)
        if "accel_x" in kwargs: self.accel[0] = kwargs["accel_x"]
        if "accel_y" in kwargs: self.accel[1] = kwargs["accel_y"]
        if "accel_z" in kwargs: self.accel[2] = kwargs["accel_z"]
        if "gyro_x"  in kwargs: self.gyro[0]  = kwargs["gyro_x"]
        if "gyro_y"  in kwargs: self.gyro[1]  = kwargs["gyro_y"]
        if "gyro_z"  in kwargs: self.gyro[2]  = kwargs["gyro_z"]

    def tick(self, dt_ms):
        # Pack injected values into register file each tick
        # so that the firmware always reads current data
        self._pack_accel()
        self._pack_gyro()

    def i2c_write(self, address, register, data):
        # Store written bytes into register file
        for i, byte in enumerate(data):
            if register + i < len(self._regs):
                self._regs[register + i] = byte & 0xFF

    def i2c_read(self, address, register, length):
        end = min(register + length, len(self._regs))
        return bytes(self._regs[register:end])

    def _pack_accel(self):
        # Convert g to raw 16-bit signed int (±2g range, sensitivity 16384 LSB/g)
        for i, (val, base) in enumerate(
                zip(self.accel, [0x3B, 0x3D, 0x3F])):
            raw = int(val * 16384)
            raw = max(-32768, min(32767, raw))
            self._regs[base]   = (raw >> 8) & 0xFF
            self._regs[base+1] = raw & 0xFF

    def _pack_gyro(self):
        # 131 LSB/(deg/s) at ±250 deg/s range
        for i, (val, base) in enumerate(
                zip(self.gyro, [0x43, 0x45, 0x47])):
            raw = int(val * 131)
            raw = max(-32768, min(32767, raw))
            self._regs[base]   = (raw >> 8) & 0xFF
            self._regs[base+1] = raw & 0xFF
```

### 4.3 SPI sensor / display

```python
class ADS1118Node(Node):
    def __init__(self, instance_id, descriptor):
        super().__init__(instance_id, descriptor)
        self._config = 0x8583    # default config register
        self._input_voltage = [0.0, 0.0, 0.0, 0.0]   # AIN0–3 (V)

    def inject(self, channel: int, voltage: float):
        self._input_voltage[channel] = voltage

    def spi_transfer(self, cs_pin, data: bytes) -> bytes:
        # SPI devices receive a command and return data simultaneously
        # Parse the incoming bytes, return the response bytes
        if len(data) < 2:
            return bytes(len(data))
        cmd = (data[0] << 8) | data[1]
        # Decode MUX bits [14:12] to select input channel
        mux = (cmd >> 12) & 0x07
        channel = mux - 4 if mux >= 4 else 0
        channel = max(0, min(3, channel))
        # Convert voltage to 16-bit signed result (±2.048V FSR, 32768 counts)
        raw = int(self._input_voltage[channel] / 2.048 * 32767)
        raw = max(-32768, min(32767, raw))
        return bytes([(raw >> 8) & 0xFF, raw & 0xFF])
```

### 4.4 Display IC

```python
class ST7789Node(Node):
    WIDTH  = 240
    HEIGHT = 320

    def __init__(self, instance_id, descriptor):
        super().__init__(instance_id, descriptor)
        self.framebuffer = bytearray(self.WIDTH * self.HEIGHT * 2)  # RGB565
        self._cmd = 0x00
        self._in_data = False
        self._write_addr = (0, 0, 0, 0)   # x0, y0, x1, y1 window

    def gpio_write(self, pin, value):
        dc_pin = self.descriptor.get("default_pins_esp32", {}).get("DC")
        if pin == dc_pin:
            self._in_data = bool(value)

    def spi_transfer(self, cs_pin, data: bytes) -> bytes:
        # First byte after DC=LOW is a command; bytes after DC=HIGH are data
        for byte in data:
            if not self._in_data:
                self._cmd = byte
                self._handle_command(byte)
            else:
                self._handle_data(byte)
        return bytes(len(data))

    def _handle_command(self, cmd): ...
    def _handle_data(self, byte): ...

    def get_pixel(self, x, y) -> int:
        idx = (y * self.WIDTH + x) * 2
        return (self.framebuffer[idx] << 8) | self.framebuffer[idx+1]
```

### 4.5 MCU node

```python
from firmware.shim.pin_map import PinMap
from firmware.shim.arduino_api import ArduinoShim

class ESP32Node(Node):
    def __init__(self, instance_id, descriptor):
        super().__init__(instance_id, descriptor)
        self._pin_map: PinMap | None = None
        self.shim: ArduinoShim | None = None
        self._firmware = None   # set by runner before first tick

    def attach(self, netlist, bus, runner):
        # Called by runner after load_netlist()
        self._pin_map = PinMap(self.id, netlist, self.descriptor)
        self.shim = ArduinoShim(
            node_id=self.id,
            bus=bus,
            runner=runner,
            pin_map=self._pin_map,
            adc_bits=12,
            adc_vref=3.3,
        )

    def load_firmware(self, setup_fn, loop_fn):
        self._firmware = (setup_fn, loop_fn)

    def run_setup(self):
        if self._firmware:
            self._firmware[0](self.shim)

    def run_loop(self):
        if self._firmware:
            self._firmware[1](self.shim)

    def reset(self):
        if self.shim:
            self.shim._pin_modes.clear()
```

---

## 5. Extracting Data from Datasheets

This section explains how to read a datasheet and produce a correct descriptor
and model. Follow each step in order.

### Step 1 — Identify the part and protocol

Open the datasheet. In the first two pages, find:

- **Part number** (exact, including package variant if relevant) → `"part"`
- **Interface** (I2C, SPI, UART, GPIO) → `"protocol"`
- **Supply voltage range** (min/max/nominal) → `"vdd_min"`, `"vdd_max"`, `"vdd_nom"`
- **Supply current** (typical, from electrical characteristics table) → `"idd_ua"`

### Step 2 — Extract the pin table

Find the **Pin Description** or **Pin Configuration** table. It lists every pin
with name, number, and function. For each pin:

1. Map the function to one of the pin types in the schema above.
2. Note any special conditions (e.g. "pull HIGH for address 0x69", "active low reset").
3. Note which pins are configurable (address pins, mode select pins).

**For ICs with many pins** (MCUs especially): you only need to list the pins
that affect simulation behaviour. NC (no-connect) pins can be listed as `"type": "nc"`
in bulk without detail.

### Step 3 — Extract the I2C address (I2C parts)

Find the **Serial Interface** or **I2C Address** section. This tells you:
- The 7-bit base address (e.g. `0x68`)
- Which pin(s) select the alternate address
- The range of possible addresses if multiple address pins exist

Write the default address into `i2c.address_default`. If the address changes
based on a pin, note the pin name in `i2c.address_pin` and both addresses.

**AD0/ADDR pin pattern** (very common):
```
AD0 = GND → address = 0x68
AD0 = VDD → address = 0x69
```

### Step 4 — Extract the register map (I2C / SPI register-based parts)

Find the **Register Map** section. You do not need to model every register.
Identify only the registers that:

a) The firmware you will test reads or writes.
b) Control the operating mode (power management, config registers).
c) Contain the output data your model needs to produce (measurement registers).

For each relevant register, note:
- Address (hex)
- Name
- Reset value (hex) — your `__init__` must set `self._regs[addr] = reset_value`
- Bit fields you care about (read the field description, not just the bit table)

**Scale factors** — the most common source of bugs. For every measurement register:
- Find the **sensitivity** or **LSB weight** in the electrical characteristics table
- This gives you the formula: `raw_value = physical_value / sensitivity`
- Example: MPU6050 accelerometer at ±2g range has sensitivity 16384 LSB/g
  → `raw = int(accel_g * 16384)` and it must fit in a signed 16-bit integer

### Step 5 — Extract SPI transaction format (SPI parts)

Find the **SPI Interface** or **Timing Diagrams** section. You need:

- **Clock mode** (CPOL, CPHA → mode 0, 1, 2, or 3) → `spi.mode`
- **Maximum clock speed** → `spi.max_speed_hz`
- **Word size** (almost always 8 bits) → `spi.word_size`
- **Transaction format**: what bytes does the master send, what does the device return?

Draw out the transaction byte-by-byte. Example for ADS1115 in SPI mode:
```
Master → [CMD_HIGH, CMD_LOW]    ← config register write
Slave  → [RESULT_HIGH, RESULT_LOW]  ← previous conversion result
```
This is the format your `spi_transfer()` method must implement.

### Step 6 — Extract thermal data

Find the **Package / Thermal Characteristics** section. Look for:
- **θJA** (theta JA) — junction-to-ambient thermal resistance in °C/W
  → `"thermal_resistance_c_per_w"`
- If θJA is not given, use these estimates:
  - SOT-23, SC-70 (tiny): 250–400 °C/W
  - SOIC-8: 125–160 °C/W
  - QFN-16 to QFN-32: 30–60 °C/W
  - LQFP-48 to LQFP-100: 40–80 °C/W
  - TO-220 (with heatsink tab): 5–15 °C/W

Thermal capacitance is rarely in datasheets. Use:
- Small SMD IC (≤ 5mm²): 0.1–0.3 J/°C
- Medium IC (5–15mm²): 0.5–1.0 J/°C
- Large IC / MCU module: 1.0–5.0 J/°C

### Step 7 — For MCU parts: build the gpio_map

Find the **Pin Multiplexing** or **GPIO Matrix** appendix. This is the largest
table in any MCU datasheet. For each GPIO number:

1. Find its KiCad pin name in the KiCad symbol (`*.kicad_sym` file) — it is
   usually `IOxx` or `GPIOxx`.
2. Note every peripheral function it can serve (ADC, DAC, UART, SPI, I2C, PWM).
3. Note input-only pins explicitly — the shim will reject `OUTPUT` mode on these.

**ESP32-specific:** GPIO 34, 35, 36, 39 are input-only. GPIOs 25 and 26 have
the DAC. GPIOs 32–39 have ADC1; GPIOs 0, 2, 4, 12–15, 25–27 have ADC2
(ADC2 cannot be used when WiFi is active, but for simulation purposes treat
all ADC pins equivalently).

---

## 6. Registering a Part

After writing the descriptor and model, register the part so the runner can
auto-instantiate it from a netlist.

In your part's `model.py`, add a module-level registration call at the bottom:

```python
# parts/mpu6050/model.py  — bottom of file

import core.registry as registry

registry.register_part(
    "InvenSense:MPU-6050",          # KiCad lib_id — check your schematic
    MPU6050Node,
    i2c_address=0x68,
)

# If the same IC appears under multiple lib_ids in different KiCad libraries:
registry.register_part("Sensor_IMU:MPU-6050", MPU6050Node, i2c_address=0x68)
```

Then import the model somewhere before calling `runner.load()`:

```python
import parts.mpu6050.model    # side-effect: registers the part
from core.runner import SimRunner

runner = SimRunner()
runner.load("my_board.kicad_sch")
```

To find the correct `lib_id` for your part, open the schematic in KiCad,
click the component, and read the `lib_id` field in the symbol properties.
It is always in the format `"LibraryName:PartName"`.

---

## 7. Naming Conventions

| Thing | Convention | Example |
|---|---|---|
| Part directory | lowercase, hyphens | `esp32-wroom-32`, `ads1115` |
| Node class name | PascalCase + `Node` suffix | `MPU6050Node`, `ADS1115Node` |
| `PART_ID` attribute | matches directory name | `"ads1115"` |
| Descriptor keys | snake_case | `"thermal_resistance_c_per_w"` |
| Register constants | `REG_` prefix, ALL_CAPS | `REG_PWR_MGMT_1 = 0x6B` |
| Injectable fields | descriptive, snake_case | `self.accel`, `self.temperature_c` |
| `inject()` kwargs | match field names | `node.inject(temperature_c=50.0)` |
| KiCad lib_id registration | exact string from schematic | `"Sensor_IMU:MPU-6050"` |

---

## 8. Worked Examples

### Example A — Simple I2C sensor (ADS1115, 16-bit ADC)

**From the datasheet:**
- Protocol: I2C
- Address: 0x48 (ADDR=GND), 0x49 (ADDR=VDD), 0x4A (ADDR=SDA), 0x4B (ADDR=SCL)
- Registers: Config (0x01), Conversion (0x00), Lo_thresh (0x02), Hi_thresh (0x03)
- Config reset value: 0x8583
- Full-scale range: ±2.048V at default PGA setting → 32767 LSB = 2.048V
- Sensitivity at ±2.048V: 2.048V / 32767 = 62.5 µV/LSB

**descriptor.json (excerpt):**
```json
{
  "part": "ADS1115",
  "protocol": "I2C",
  "i2c": { "address_default": "0x48", "address_pin": "ADDR", "speed_max_khz": 400 },
  "registers": {
    "0x00": { "name": "CONVERSION",  "note": "16-bit signed result" },
    "0x01": { "name": "CONFIG",      "reset_value": "0x8583" }
  }
}
```

**model.py key logic:**
```python
def i2c_read(self, address, register, length):
    if register == 0x00:   # CONVERSION register
        channel = (self._config >> 12) & 0x07  # MUX[14:12]
        ch = max(0, (channel - 4) if channel >= 4 else 0)
        raw = int(self.input_voltage[ch] / 2.048 * 32767)
        raw = max(-32768, min(32767, raw))
        return bytes([(raw >> 8) & 0xFF, raw & 0xFF])
    return bytes(length)
```

### Example B — SPI display (finding the transaction format)

**Datasheet says** (ST7789 section 8.3):
> Write cycle: CS low, D/CX low for command byte, D/CX high for data bytes, CS high.
> RAMWR (0x2C): followed by pixel data, 2 bytes per pixel, RGB565.

**model.py key logic:**
```python
def gpio_write(self, pin, value):
    if pin == self._dc_pin:
        self._is_data = bool(value)

def spi_transfer(self, cs_pin, data):
    for byte in data:
        if not self._is_data:
            self._current_cmd = byte   # command phase
        else:
            self._write_pixel_byte(byte)   # data phase
    return bytes(len(data))
```

### Example C — MCU gpio_map (ESP32-WROOM-32, partial)

**From ESP32 datasheet Table 9 + KiCad symbol pin names:**

| GPIO | KiCad pin name | Capabilities |
|---|---|---|
| 0 | IO0 | digital_in, digital_out, pwm, adc |
| 2 | IO2 | digital_in, digital_out, pwm, adc |
| 18 | IO18 | digital_in, digital_out, pwm, spi |
| 21 | IO21 | digital_in, digital_out, i2c |
| 25 | IO25 | digital_in, digital_out, dac, pwm |
| 34 | IO34 | digital_in, adc, **input_only** |

```json
"gpio_map":  { "18": "IO18", "21": "IO21", "34": "IO34" },
"pin_caps":  {
  "18": ["digital_in", "digital_out", "pwm", "spi"],
  "21": ["digital_in", "digital_out", "i2c"],
  "34": ["digital_in", "adc", "input_only"]
}
```

---

*End of Part Authoring Guide.*
*When in doubt, check the datasheet first, then check how an existing part implements the same pattern.*
