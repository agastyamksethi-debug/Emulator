# PCB Simulator — Part Authoring Guide

This document defines the exact file format and contract every part must
follow so the simulator can auto-instantiate it from a KiCad schematic.
It is written to be handed to any person or model — if you follow every
section in order, the resulting part will work without modification.

---

## How a Part Is Used at Runtime

When `SimRunner.load("board.kicad_sch")` is called:

1. The KiCad schematic is parsed into a netlist (components + nets).
2. For every IC component found, its `lib_id` is looked up in the registry.
3. If a match is found, the corresponding `Node` class is instantiated using
   the part's `descriptor.json`.
4. Each node is attached to the bus (I2C, SPI, GPIO, UART) based on its
   descriptor fields.
5. Pin-to-net mappings are resolved so the shim can route firmware API calls
   to the correct bus nets.

This means `descriptor.json` is not documentation — the simulator reads it
directly. Every field has a functional effect. Missing required fields cause
the part to fail to load.

---

## 1. Part Classifications

Pick exactly one. This determines which Node methods you must implement.

| Classification | Ref prefix | Needs `model.py` | Description |
|---|---|---|---|
| MCU | `U` | Yes — complex | Runs firmware via Arduino shim |
| Sensor | `U` | Yes | Register map + injectable measurement values |
| Display / Output IC | `U` | Yes | Framebuffer or output state, no rendering |
| Interface IC | `U` | Yes | Protocol bridge or converter behaviour |
| Power IC | `U` | Yes — simple | Subclass `RegulatorNode` or `BatteryNode` |
| Transistor | `Q` | Yes — simple | Threshold / switch model |
| Diode / LED | `D`, `LED` | **No** | Auto-handled by `physics/passive.py` |
| Passive | `R`, `C`, `L`, `FB` | **No** | Auto-handled by `physics/passive.py` |
| Connector | `J` | **No** | Inert — nets pass straight through |
| Crystal / Oscillator | `Y`, `X` | **No** | Assumed always-on clock source |

Passives, connectors, crystals, and diodes/LEDs need a `descriptor.json` only
if you want thermal tracking — they never need a `model.py`.

For diodes and LEDs the simulator detects the forward voltage (Vf) automatically
from the KiCad value string: Schottky → 0.3 V, LED → 2.0 V, silicon → 0.7 V,
Zener/TVS → skipped. If a diode needs non-standard Vf or additional behaviour
(e.g. a specific clamp voltage), create a `model.py` and register it; the
passive auto-handler is bypassed when a registered class exists for that lib_id.

---

## 2. Directory and File Structure

```
parts/
  <part-name>/
    descriptor.json     ← REQUIRED for every part
    model.py            ← REQUIRED for all active parts (see table above)
    arduino/            ← REQUIRED for MCU parts only
      <LibName>.h
      library.properties
      keywords.txt
      examples/
        <ExampleName>/
          <ExampleName>.ino
```

**Naming rules**
- `<part-name>`: lowercase, hyphens only, use the IC part number exactly.
  Examples: `mpu-6050`, `ads1115`, `esp32-wroom-32`, `ina226`.
- The `<part-name>` directory name must match the `PART_ID` constant in
  `model.py` and the `parts.<part-name>.model` path in `descriptor.json`.

---

## 3. `descriptor.json` — Complete Field Reference

All fields and their exact effect on the simulator are described below.
**REQUIRED** fields are mandatory. Optional fields improve accuracy but have
safe defaults where noted.

```jsonc
{
  // ─────────────────────────────────────────────────────────────
  // IDENTITY
  // Used for display, error messages, and registry lookup.
  // ─────────────────────────────────────────────────────────────

  "part": "<MANUFACTURER_PART_NUMBER>",
  // REQUIRED. Exact string from the datasheet cover page.
  // Use the base part number — omit temperature/package suffixes.

  "manufacturer": "<COMPANY_NAME>",
  // REQUIRED. Manufacturer name as printed on the datasheet.

  "description": "<one-line description including protocol>",
  // REQUIRED. E.g. "16-bit ADC, I2C, 4-channel" or "32-bit MCU, WiFi+BT, SPI/I2C/UART".

  "classification": "<see section 1 table>",
  // REQUIRED. Must be one of: MCU, Sensor, Display, Interface, Power, Discrete,
  // Passive, Connector, Crystal.

  "protocol": "<primary bus>",
  // REQUIRED. I2C | SPI | UART | GPIO | SPI+GPIO | none
  // Use "SPI+GPIO" when both SPI data and separate GPIO control pins are needed.

  "datasheet": "<URL or filename>",
  // URL to the datasheet PDF, or a local filename if saved in the part directory.


  // ─────────────────────────────────────────────────────────────
  // PACKAGE
  // ─────────────────────────────────────────────────────────────

  "package": "<JEDEC-package-name>",
  // REQUIRED. Standard package name, e.g. "SOIC-8", "QFN-24", "TO-220", "BGA-48".
  // Find this in the datasheet ordering information or package outline section.

  "visual": {
    "width_mm": 0.0,
    "height_mm": 0.0,
    "color": "#2a2a2a"
  },
  // Optional. Physical size from the package outline drawing.
  // Used by UI renderers — has no effect on electrical simulation.


  // ─────────────────────────────────────────────────────────────
  // ELECTRICAL
  // From the "Absolute Maximum Ratings" or "Electrical Characteristics" table.
  // ─────────────────────────────────────────────────────────────

  "vdd_min": 0.0,    // REQUIRED. Minimum VDD (V). Below this = under-voltage warning.
  "vdd_max": 0.0,    // REQUIRED. Maximum VDD (V). Above this = over-voltage warning.
  "vdd_nom": 0.0,    // Optional. Typical operating voltage.
  "idd_ua":  0,      // Optional. Typical supply current in µA (used for thermal model).


  // ─────────────────────────────────────────────────────────────
  // PINS
  //
  // Maps every pin to a functional type so the bus can route signals correctly.
  //
  // IMPORTANT: The key (e.g. "VDD", "SCL") MUST EXACTLY MATCH the pin name
  // shown in the KiCad symbol (.kicad_sch). Open the schematic, click the
  // component, read each pin label — those strings go here verbatim.
  // A mismatch means the bus cannot resolve the pin and will silently ignore it.
  //
  // Valid pin types:
  //   power       — supply voltage input pin
  //   ground      — ground pin
  //   i2c_sda     — I2C data line
  //   i2c_scl     — I2C clock line
  //   spi_cs      — SPI chip select
  //   spi_clk     — SPI clock
  //   spi_mosi    — SPI master-out / slave-in
  //   spi_miso    — SPI master-in / slave-out
  //   gpio        — bidirectional general purpose IO
  //   gpio_in     — input-only GPIO
  //   gpio_out    — output-only GPIO
  //   adc_in      — analog input pin
  //   dac_out     — analog output pin
  //   interrupt   — IRQ output (active-low unless noted)
  //   reset       — hardware reset input (active-low unless noted)
  //   address     — I2C address select pin (logic level sets address LSBs)
  //   enable      — chip enable / shutdown pin
  //   nc          — no-connect, ignored by simulator
  // ─────────────────────────────────────────────────────────────

  "pins": {
    "<KiCad-pin-name>": {
      "type": "<pin-type-from-list-above>",
      "voltage": 3.3,         // Optional — for power pins: the rail voltage this pin supplies.
      "active": "low",        // Optional — for interrupt/reset pins: polarity.
      "note": "<freeform>"    // Optional — any clarifying note.
    }
    // Add one entry for every pin on the device.
    // NC and tied pins should still be listed with type "nc".
  },


  // ─────────────────────────────────────────────────────────────
  // I2C BLOCK
  // Include only for I2C devices. Omit entirely for SPI/UART/GPIO parts.
  //
  // How it is used: the bus reads "address_default" to route i2c_write()
  // and i2c_read() calls to this node. If an address-select pin (like ADDR
  // or ADx) is present in the schematic, the bus resolves its net voltage
  // and may use "address_alt" instead.
  // ─────────────────────────────────────────────────────────────

  "i2c": {
    "address_default": "0xNN",  // REQUIRED. 7-bit I2C address, hex string.
                                 // From datasheet "Serial Bus Address" or "Device Address" table.
                                 // Include only the 7 address bits (not the R/W bit).
    "address_alt": "0xNN",      // Optional. Alternate address when address-select pin is HIGH.
                                 // Include if the device supports multiple addresses via a pin.
    "address_pin": "<pin-name>",// Optional. Name of the pin that selects the address.
                                 // Must match a pin listed in "pins" with type "address".
    "speed_max_khz": 400        // Optional. Maximum I2C clock rate from datasheet. 100 or 400 typical.
  },


  // ─────────────────────────────────────────────────────────────
  // SPI BLOCK
  // Include only for SPI devices. Omit entirely for I2C/UART/GPIO parts.
  //
  // How it is used: the bus reads "cs_pin" to identify which net assertion
  // should trigger spi_transfer() on this node. The SPI mode determines
  // how the shim configures the SPI peripheral before a transfer.
  // ─────────────────────────────────────────────────────────────

  "spi": {
    "mode": 0,              // REQUIRED. Clock polarity + phase: 0=(0,0), 1=(0,1), 2=(1,0), 3=(1,1).
                             // From the datasheet SPI timing diagram: read CPOL and CPHA values.
    "max_speed_hz": 0,      // REQUIRED. Maximum SPI clock frequency in Hz.
    "cs_pin": "<pin-name>", // REQUIRED. Pin name of chip select. Must match a pin in "pins".
    "cs_active": "low",     // Optional. "low" (default) or "high".
    "word_size": 8          // Optional. Bits per transfer word. Default 8.
  },


  // ─────────────────────────────────────────────────────────────
  // REGISTER MAP
  // Document only the registers your model actually reads or writes.
  // Omit registers that the simulation does not touch.
  //
  // How it is used: this is documentation for the model author, not
  // parsed at runtime. The model.py must implement the register behaviour
  // described here. The "reset_value" here must match what model.reset()
  // loads into the internal register dict.
  // ─────────────────────────────────────────────────────────────

  "registers": {
    "0xNN": {
      "name": "<REGISTER_NAME>",         // Datasheet register name, UPPER_SNAKE.
      "reset_value": "0x0000",           // Value after power-on or RST assertion.
      "note": "<what this register does>",
      "fields": {                        // Optional. Bit fields within the register.
        "<FIELD_NAME>": {
          "bit": 15,                     // Single bit position (0 = LSB).
          "bits": "14:12",              // OR a range "msb:lsb".
          "note": "<what this field controls>"
        }
      }
    }
    // Repeat for each register the model uses.
  },


  // ─────────────────────────────────────────────────────────────
  // MCU FIELDS
  // Include ONLY for MCU classification. Omit for all other part types.
  //
  // gpio_map: maps Arduino/firmware GPIO numbers → KiCad pin names.
  // This is what connects digitalWrite(18, HIGH) to the correct net in
  // the schematic. Without this, the shim cannot find the net.
  //
  // How to build it: open the KiCad symbol, list every GPIO pin label,
  // then find the matching logical number from the MCU datasheet's
  // "Pin Multiplexing" or "GPIO Matrix" appendix.
  // ─────────────────────────────────────────────────────────────

  "gpio_map": {
    "<gpio-number-as-string>": "<KiCad-pin-name>"
    // Example pattern — fill in all GPIO pins from your MCU:
    // "0":  "IO0",
    // "1":  "IO1",
    // "34": "IO34"
    // One entry per physical GPIO pin. String keys, string values.
  },

  // pin_caps: which capabilities each GPIO supports.
  // Used by the Arduino shim to enforce correct usage. If firmware calls
  // analogRead() on a pin not listed with "adc", SimPinError is raised.
  //
  // Valid capabilities:
  //   digital_in   — can be read as digital
  //   digital_out  — can be driven digital
  //   adc          — has ADC multiplexer connection
  //   dac          — has DAC output
  //   pwm          — has PWM/LEDC timer
  //   spi          — can be configured as SPI (MOSI/MISO/CLK/CS)
  //   i2c          — can be configured as I2C (SDA/SCL)
  //   uart         — can be configured as UART (TX/RX)
  //   input_only   — physically cannot drive output (e.g. ADC-only pads)
  //
  // Find this in the MCU datasheet's pin function table or IO matrix.

  "pin_caps": {
    "<gpio-number-as-string>": ["<cap>", "<cap>"]
    // One entry per GPIO. List every capability the pin supports.
    // Always include input_only for pads that cannot source current.
  },


  // ─────────────────────────────────────────────────────────────
  // THERMAL
  // From the "Thermal Characteristics" table in the datasheet.
  // If the datasheet does not list these, use the package estimates below.
  // ─────────────────────────────────────────────────────────────

  "thermal_resistance_c_per_w": 0.0,
  // θJA — junction-to-ambient thermal resistance in °C/W.
  // Package estimates if not in datasheet:
  //   SOT-23:     ~300 °C/W
  //   SOIC-8:     ~150 °C/W
  //   TSSOP-20:   ~100 °C/W
  //   QFN-24/32:   ~45 °C/W
  //   TO-220:      ~10 °C/W
  //   BGA:          ~20 °C/W

  "thermal_capacitance_j_per_c": 0.0,
  // Thermal mass of the package in J/°C.
  // If not in datasheet, estimate by package size:
  //   Small SMD (SOT, SOIC-8):  0.1 J/°C
  //   Medium IC (TSSOP, QFN):   0.5 J/°C
  //   Large IC (BGA, TO-220):   2.0 J/°C


  // ─────────────────────────────────────────────────────────────
  // POINTERS — how the runner finds your code
  // ─────────────────────────────────────────────────────────────

  "simulation_model": "parts.<part-name>.model.<ClassName>Node",
  // REQUIRED for all active parts. Python dotted import path to the Node class.
  // Replace <part-name> with your directory name and <ClassName> with your class.

  "arduino_library": "parts/<part-name>/arduino"
  // REQUIRED for MCU parts only. Path to the Arduino library directory.
}
```

---

## 4. `model.py` — Node Subclass Contract

The Node class is the runtime representation of the part. The bus calls its
methods directly — the method signatures below are the exact interface the bus
expects. Do not rename arguments or change return types.

### 4.1 Base — every active part must implement

```python
from core.node import Node

class <ClassName>Node(Node):
    PART_ID = "<part-name>"   # must match the parts/ directory name

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        # Declare all internal state variables here.
        # Do NOT open files, start threads, or call bus methods.

    def reset(self):
        # Restore every internal register to its descriptor "reset_value".
        # Must be callable multiple times without side effects.
        # The runner calls reset() after instantiation and after a simulated RST.
        pass

    def tick(self, dt_ms: float):
        # Advance internal time-dependent state by dt_ms milliseconds.
        # Example uses: timeout counters, conversion-in-progress flags,
        # watchdog timers, FIFO aging.
        # Do NOT call bus read/write methods here.
        pass
```

### 4.2 I2C sensor/IC — add these methods

The bus calls these when firmware issues `Wire.write()` / `Wire.requestFrom()`.

```python
    i2c_address: int = 0x00   # Set to address_default from descriptor.
                               # If the part has an address-select pin,
                               # override this in __init__ after reading
                               # the pin net voltage from the bus.

    def i2c_write(self, address: int, register: int, data: bytes) -> None:
        # Called when the MCU writes to this device.
        # 'register' is the first byte the MCU sent (the register pointer).
        # 'data' is every byte after that.
        # Store data into your internal register file starting at 'register'.
        # For write-only bits (e.g. config write triggers a hardware action),
        # decode the config and update internal state accordingly.
        pass

    def i2c_read(self, address: int, register: int, length: int) -> bytes:
        # Called when the MCU reads from this device.
        # Return exactly 'length' bytes from your register file starting
        # at 'register'. The format (endianness, signed/unsigned) must
        # match what the real device returns per the datasheet.
        return bytes(length)

    def inject(self, **kwargs) -> None:
        # Test hook: set the physical quantity the sensor is measuring.
        # kwargs are part-specific (e.g. temperature_c=25.0, voltage_v=3.3).
        # Store them and have tick() or i2c_read() pack them into the
        # output register using the sensitivity/LSB scale from the datasheet.
        pass
```

**Sensors with an interrupt pin** — implement `attach()` to get bus access,
then drive the INT net from `tick()`:

```python
    def attach(self, netlist, bus, runner) -> None:
        self._bus = bus
        # Read the net name that the INT pin is connected to in the schematic.
        # Replace "INT" with the exact KiCad pin name from the symbol.
        comp = netlist.components.get(self.id, {})
        self._int_net = comp.get("pins", {}).get("INT", "")

    def tick(self, dt_ms: float) -> None:
        # ... update internal state, set self._data_ready ...
        if self._int_net:
            if self._data_ready:
                self._bus.drive_digital(self._int_net, self.id, False)  # pull INT low
            else:
                self._bus.release(self._int_net, self.id)               # release INT
```

The MCU firmware calls `attachInterrupt(pin, callback, FALLING)` on the GPIO
that connects to this net. The simulator fires the callback at the end of the
tick in which INT transitions from HIGH to LOW.

### 4.3 SPI sensor/IC — add these methods

The bus calls these when the MCU asserts the CS net and calls `SPI.transfer()`.

```python
    def spi_transfer(self, cs_pin: int, data: bytes) -> bytes:
        # Full-duplex: 'data' is what the MCU sent (MOSI bytes).
        # Return the same number of bytes (MISO bytes).
        # Parse the command from data[0] (usually read/write bit + register addr),
        # then build the response from your internal register file.
        # Must return bytes of exactly len(data).
        return bytes(len(data))

    def gpio_write(self, pin: int, value: int) -> None:
        # Called when the MCU drives a GPIO that connects to this part.
        # Handle control pins such as:
        #   - D/C (data/command selector on displays)
        #   - RST (reset assertion — call self.reset() when RST goes low)
        #   - EN or SHDN (enable/shutdown lines)
        # 'pin' is the GPIO number from the MCU's gpio_map.
        # 'value' is 0 (LOW) or 1 (HIGH).
        pass
```

### 4.4 MCU — add these methods

The runner calls `attach()` once after netlist load. Firmware is loaded
separately and called by the runner's tick loop.

```python
    def attach(self, netlist, bus, runner) -> None:
        # Build the PinMap and ArduinoShim that all firmware calls go through.
        # This must be called before load_firmware().
        from firmware.shim.pin_map import PinMap
        from firmware.shim.arduino_api import ArduinoShim
        self._pin_map = PinMap(self.id, netlist, self.descriptor)
        self.shim = ArduinoShim(
            node_id=self.id,
            bus=bus,
            runner=runner,
            pin_map=self._pin_map,
            adc_bits=<N>,        # resolution from datasheet, e.g. 12
            adc_vref=<V>,        # reference voltage from datasheet, e.g. 3.3
        )

    def load_firmware(self, setup_fn, loop_fn) -> None:
        # Accept the two Arduino-style firmware functions.
        # setup_fn(shim) and loop_fn(shim) will be called by the runner.
        self._firmware = (setup_fn, loop_fn)

    def run_setup(self) -> None:
        if self._firmware:
            self._firmware[0](self.shim)

    def run_loop(self) -> None:
        if self._firmware:
            self._firmware[1](self.shim)
```

### 4.5 Display / output IC — additional requirement

Keep a framebuffer or output state as a plain Python object (`bytearray`,
list, dict). Do not render or open windows — the consumer reads state via
these methods:

```python
    def get_framebuffer(self) -> bytearray:
        # Return the raw pixel buffer. Width × height × bytes_per_pixel.
        ...

    def get_pixel(self, x: int, y: int) -> int:
        # Return the pixel value at (x, y) in the device's native format.
        ...
```

### 4.6 Power IC — use the provided base classes

Do not write a voltage source from scratch. Subclass the appropriate base from
`physics/voltage_source.py` and override only what differs:

```python
from physics.voltage_source import RegulatorNode, BatteryNode

class MyLDONode(RegulatorNode):
    PART_ID = "<part-name>"

    def __init__(self, instance_id: str, descriptor: dict):
        # Read v_out and v_dropout from the descriptor if present,
        # otherwise hard-code from the datasheet.
        super().__init__(
            instance_id,
            input_net  = "<input-rail-net-name>",   # resolved at runtime
            output_net = "<output-rail-net-name>",
            v_out      = 3.3,    # nominal output voltage (V)
            v_dropout  = 0.3,    # minimum headroom required (V)
            i_limit_a  = 0.5,    # current limit (A)
        )
```

```python
class MyBatteryNode(BatteryNode):
    PART_ID = "<part-name>"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(
            instance_id,
            output_net   = "<output-net-name>",
            v_full       = 4.2,     # fully charged terminal voltage (V)
            v_empty      = 3.0,     # cut-off voltage (V)
            capacity_mah = 2000.0,  # rated capacity
            internal_resistance = 0.1,  # Ω — from datasheet or measured
        )
```

`RegulatorNode.tick()` automatically drops the output when the input sags below
`v_out + v_dropout`. `BatteryNode.tick()` tracks state-of-charge and drapes
the terminal voltage linearly between `v_full` and `v_empty`.

Add with `runner.add_node(node)` — do not register in the part registry unless
the part appears in KiCad schematics as a component with a lib_id.

### 4.7 Rules enforced across all models

| Rule | Reason |
|---|---|
| `__init__` must call `super().__init__(instance_id, descriptor)` | Base class reads descriptor and sets `self.id`, `self.temperature`, `self.power_dissipation`. |
| `reset()` must match every "reset_value" in descriptor registers | Firmware often reads these at startup to verify the device is alive. |
| `tick()` must return quickly | It runs every simulation step — avoid slow loops. |
| `inject()` must exist on every sensor | Test harnesses call it unconditionally. |
| No file I/O, threading, or UI inside any method | Models run headless and must be thread-safe-adjacent. |
| Register packing must match the datasheet byte order | Wrong endianness causes silent read failures in firmware. |

---

## 5. Extracting What You Need from a Datasheet

This is a systematic process. Work through each step in order for every new
part. Stop at any step that does not apply to the part's classification.

---

### Step 1 — Identity, classification, and protocol

**Where:** First one or two pages. Product description, features list, ordering
information.

**Extract:**
- Exact part number (omit suffixes for temperature grade and package)
- The primary communication protocol: I2C, SPI, UART, or GPIO-only
- Supply voltage range: look for "VDD", "VCC", or "Supply Voltage" in the
  Absolute Maximum Ratings table. Take V_min and V_max from the Operating
  Conditions sub-table, not the Absolute Max.
- Typical supply current: usually labelled I_DD or I_CC in µA or mA.

**Fills:** `part`, `manufacturer`, `classification`, `protocol`, `vdd_min`,
`vdd_max`, `vdd_nom`, `idd_ua`.

---

### Step 2 — Pin table

**Where:** "Pin Configuration", "Pin Description", or "Package Pinout" section.
Typically a numbered table with columns: Pin No., Name, Type, Description.

**Extract:**
- Every pin name — these must match the KiCad symbol exactly. Open the
  `.kicad_sch` file and verify; the symbol author may have renamed or
  abbreviated pins.
- Pin direction (input, output, bidirectional, power).
- Note any pins that are active-low (usually denoted with an overline in the
  datasheet or a `/` prefix like `/CS`, `/RST`, `/INT`).
- Note which pins control the I2C address (commonly named ADDR, AD0, SA0,
  A0/A1/A2 etc.).

**Fills:** Every entry in `"pins": {}`.

---

### Step 3 — I2C device address

**Where:** "I2C Interface", "Serial Bus Address", or "Device Address" section.
There is always a table or formula.

**Extract:**
The datasheet specifies the 7-bit address as a fixed base with optional LSBs
set by one or more address-select pins. The format varies by manufacturer but
the pattern is always the same: a binary address word where some bits are fixed
and some bits come from pin logic levels.

To find the two (or more) valid addresses:
1. Locate the binary representation of the 7-bit address. The fixed bits give
   the base; the variable bits are replaced by the pin state.
2. For each combination of the address pin(s) being LOW or HIGH, compute the
   full 7-bit address and convert to hex.
3. Record `address_default` as the address when all address pins are LOW (or
   at their default/unconnected state as noted in the datasheet).
4. Record `address_alt` for the next combination.
5. If there are multiple address pins (A0, A1, A2), there may be up to 8
   valid addresses — list the default and note the pattern.

**Fills:** `i2c.address_default`, `i2c.address_alt`, `i2c.address_pin`,
`i2c.speed_max_khz`.

---

### Step 4 — SPI transaction format

**Where:** "SPI Interface", "Serial Interface", or "Digital Interface" section.
Look for timing diagrams showing CS, SCLK, MOSI, MISO waveforms with byte
annotations.

**Extract:**

1. **Clock mode** — find CPOL and CPHA values in the text or timing diagram:
   - CPOL=0, CPHA=0 → SPI mode 0
   - CPOL=0, CPHA=1 → SPI mode 1
   - CPOL=1, CPHA=0 → SPI mode 2
   - CPOL=1, CPHA=1 → SPI mode 3

2. **Transaction structure** — draw out one complete transaction from the
   timing diagram. Note:
   - How many bytes does the master send before the device responds?
   - What does byte 0 encode? (Usually: read/write bit + register address.)
   - Are register addresses 7-bit (leaving bit 7 for R/W) or 8-bit with a
     separate command byte before?
   - How many bytes of response per register?
   - Can multiple registers be read in one burst (auto-increment)?

3. **Maximum clock speed** — from the timing diagram parameter table, look for
   f_SCK or f_SCLK (max).

Your `spi_transfer()` implementation must parse and produce bytes that match
this transaction format exactly. Wrong byte order or missing the R/W bit are
the two most common bugs.

**Fills:** `spi.mode`, `spi.max_speed_hz`, `spi.cs_pin`, `spi.word_size`.

---

### Step 5 — Register map

**Where:** "Register Map", "Register Description", or "Memory Map" section.
Usually a large table near the end of the datasheet.

**Extract only the registers your model will simulate:**
- Config registers: the ones firmware writes to set measurement range, mode,
  resolution, sample rate. Your `i2c_write()` / `spi_transfer()` must decode
  these and update internal state.
- Output registers: the ones that hold the measurement result. Your `tick()`
  must pack the current injected value into these on every step.
- Status registers: any register firmware polls to check "data ready" or
  "conversion complete". Your model must set the relevant bits when data is
  ready.

**For each output register, find the LSB weight / sensitivity:**

```
This is the most important number in the entire datasheet for a sensor model.

It is usually in the "Electrical Characteristics" table, labelled:
  "Full-scale range", "Resolution", "LSB weight", or "Sensitivity".

The formula is always:
  raw_value = int(physical_quantity / lsb_weight)

Example pattern (fill in from your datasheet):
  If a register holds temperature in units of 0.0625 °C per LSB,
  then 25 °C → raw = int(25.0 / 0.0625) = 400 = 0x0190.

Getting this wrong produces readings that are off by a constant factor
and is the most common bug when authoring a sensor part.
```

**Fills:** `registers` block in descriptor. LSB weights go into model.py
`inject()` and `tick()` as numeric constants with a comment citing the
datasheet table and value.

---

### Step 6 — Thermal characteristics

**Where:** "Thermal Characteristics", "Thermal Information", or "Package
Thermal Resistance" section.

**Extract:**
- θJA (junction-to-ambient, °C/W) — the thermal resistance from die to
  ambient air in still air. If the table lists multiple values (different board
  conditions), use the "high-K" or "standard" condition row.
- Thermal capacitance (J/°C) — often not listed. Use package size estimate
  from the descriptor schema if absent.

**Fills:** `thermal_resistance_c_per_w`, `thermal_capacitance_j_per_c`.

---

### Step 7 — MCU GPIO mapping (MCU parts only)

**Where:** "Pin Multiplexing Table", "GPIO Matrix", "Peripheral Assignment", or
"IO MUX" appendix. Usually one of the last sections in the datasheet.

**Extract for every GPIO pin:**

1. The logical GPIO number (the number used in firmware: `digitalWrite(N)`).
2. The KiCad pin name from the KiCad symbol file (`.kicad_sym`). Open it and
   read the `pin name` fields directly — do not infer from the datasheet alone
   because symbol authors sometimes use different labels.
3. Every peripheral function the pin can be assigned to (SPI, I2C, UART, ADC,
   DAC, PWM).
4. Whether the pin is input-only (no output driver — common on ADC-only pads).

**Fills:** `gpio_map` and `pin_caps` blocks.

---

## 6. Registering a Part

At the bottom of `model.py`, register the part so the runner can
auto-instantiate it when it appears in a schematic:

```python
import core.registry as registry

registry.register_part(
    "<Library>:<PartName>",   # KiCad lib_id — read from your .kicad_sch file
    <ClassName>Node,
    i2c_address=0xNN,         # include only for I2C parts
)
```

**Finding the `lib_id`:**
Open the `.kicad_sch` file in a text editor and search for the component.
The `lib_id` field looks like:

```
(lib_id "SensorLibrary:MPU-6050")
```

The string in quotes — `"SensorLibrary:MPU-6050"` — is exactly what goes in
`register_part()`. It is case-sensitive.

**Triggering registration:**
Import the model module before calling `runner.load()`. The `register_part()`
call at module level runs as a side effect of the import:

```python
import parts.<part-name>.model   # registers the part
from core.runner import SimRunner

runner = SimRunner()
runner.load("board.kicad_sch")
```

---

## 7. Naming Conventions

| Thing | Rule | Reason |
|---|---|---|
| Part directory | lowercase, hyphens, IC part number | Must match `PART_ID` and `simulation_model` path |
| Node class name | PascalCase + `Node` suffix | Distinguishes node classes from other objects |
| `PART_ID` constant | Exact match to directory name | Used for logging and registry lookup |
| Register address constants | `REG_` prefix, UPPER_SNAKE | Makes `i2c_write()` code readable |
| Internal measurement fields | `self.<quantity>_<unit>` | Makes `inject()` kwargs self-documenting |
| `inject()` keyword args | Match internal field names exactly | Test code discovers them by inspection |
| KiCad `lib_id` string | Exact copy from `.kicad_sch` | Case-sensitive — one character off = silent miss |

---

## 8. Checklist Before Committing a Part

- [ ] `descriptor.json` has all REQUIRED fields
- [ ] Every pin name in `"pins"` matches the KiCad symbol label character for character
- [ ] I2C/SPI block present and matches the datasheet address/mode
- [ ] Register reset values in descriptor match what `model.reset()` loads
- [ ] `inject()` parameters are named `<quantity>_<unit>` (e.g. `temperature_c`)
- [ ] LSB weight / sensitivity constant is cited with the datasheet table name in a comment
- [ ] `spi_transfer()` / `i2c_read()` byte order matches the datasheet timing diagram
- [ ] `PART_ID` matches the directory name exactly
- [ ] `simulation_model` path in descriptor resolves to the actual class
- [ ] `register_part()` call is at the bottom of `model.py` with the correct `lib_id`
- [ ] For MCU parts: `gpio_map` covers all GPIO pins, `pin_caps` flags all input-only pins
- [ ] For sensors with an INT pin: `attach()` resolves `_int_net`; `tick()` drives it LOW when data is ready and releases it otherwise
- [ ] For power IC parts: subclasses `RegulatorNode` or `BatteryNode`; constructor parameters match the datasheet
- [ ] D/LED parts with non-standard Vf or extra behaviour have a registered `model.py`; otherwise no model is needed
