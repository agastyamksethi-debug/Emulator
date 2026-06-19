# ESP32-WROOM-32 Simulation Model

Complete, end-to-end simulation model for the ESP32-WROOM-32 dual-core microcontroller with WiFi and Bluetooth capabilities.

## Overview

This model provides a fully functional simulation of the **Espressif ESP32-WROOM-32**, including:

- **34 GPIO pins** with full I/O capabilities
- **Dual ADC (Analog-to-Digital Converter)**: 2×12-bit, 18 channels total
  - ADC1: 8 channels (GPIO32-39, 36, 37, 38)
  - ADC2: 10 channels (GPIO0, 2, 4, 12-15, 25-27)
  - Configurable attenuation: 0dB, 2.5dB, 6dB, 11dB
  - Sampling up to 200 kHz
  - LSB: 0.805 mV

- **Dual DAC (Digital-to-Analog Converter)**: 2×8-bit
  - DAC1: GPIO25 (0-3.3V)
  - DAC2: GPIO26 (0-3.3V)
  - Settling time: ~10 µs
  - Resolution: 12.9 mV per step

- **16-channel LEDC (PWM)** with 4 timers
  - Frequency: 10 Hz to 80 MHz
  - Resolution: up to 20 bits
  - GPIO-configurable outputs

- **3 UART interfaces** (0, 1, 2)
  - Default baud: 115200
  - Max speed: 5 Mbps
  - 128-byte FIFO each
  - Configurable data/stop bits and parity

- **2 I2C interfaces**
  - Speed: up to 1 MHz (high-speed mode)
  - Standard I2C (100 kHz), Fast (400 kHz), High (1 MHz)

- **3 SPI interfaces**
  - Speed: up to 80 MHz
  - Full-duplex operation
  - DMA support (up to 4092 bytes)

- **4 General-purpose 64-bit timers**
  - Configurable divider
  - Alarm-based interrupts
  - Autoreload capability

- **2 Watchdog timers**
  - Configurable timeout
  - System reset on overflow

- **10 Capacitive touch sensor channels**
  - 4-bit resolution
  - Threshold-based triggering

- **System features**
  - 240 MHz dual-core processor
  - 80 MHz APB clock
  - 520 KB SRAM internal
  - 8 KB RTC memory
  - Configurable sleep modes (light, deep)
  - Thermal simulation
  - Current consumption tracking

## Directory Structure

```
esp32-wroom-32/
├── descriptor.json          # Complete hardware specification
├── model.py                 # MCU simulation logic
└── arduino/
    ├── library.properties   # Arduino library metadata
    ├── keywords.txt         # IDE syntax highlighting
    ├── ESP32.h              # Arduino API header
    └── examples/
        ├── Blink/
        ├── ADC_DAC/
        └── PWM_LEDC/
```

## Key Specifications

### Electrical Characteristics

| Parameter | Min | Nom | Max | Unit |
|-----------|-----|-----|-----|------|
| VDD | 2.3 | 3.3 | 3.6 | V |
| Supply Current (idle) | - | 10 | 20 | mA |
| Supply Current (WiFi RX) | 80 | 90 | 100 | mA |
| Supply Current (WiFi TX) | 120 | 140 | 150 | mA |
| Chip Temperature Range | -40 | 25 | 125 | °C |
| Thermal Resistance (θJA) | - | 25 | - | °C/W |

### GPIO Pin Capabilities

| GPIO | Modes | Notes |
|------|-------|-------|
| 0-3 | Digital I/O, UART, ADC, PWM | General purpose pins |
| 4, 25 | Digital I/O, DAC, ADC, PWM | Dual 8-bit DAC |
| 5, 12-15, 18-23 | Digital I/O, SPI, PWM, ADC | SPI peripheral pins |
| 16, 17 | Digital I/O, UART, PWM | UART pins (default UART2) |
| 21, 22 | Digital I/O, I2C, PWM | I2C peripheral pins |
| 32-39 | ADC (input-only) | No digital output |
| 36, 39 | ADC (VP, VN) | Input-only, no GPIO output |

### ADC Specifications

**ADC1 Channels:**
- Channel 0: GPIO36 (VP)
- Channel 1: GPIO37
- Channel 2: GPIO38
- Channel 3: GPIO39 (VN)
- Channel 4: GPIO32
- Channel 5: GPIO33
- Channel 6: GPIO34
- Channel 7: GPIO35

**ADC2 Channels:**
- Channels 0-9: GPIO4, GPIO0, GPIO2, GPIO15, GPIO13, GPIO12, GPIO14, GPIO27, GPIO25, GPIO26

**Attenuation Ranges:**
- 0dB: 0 - 1.1V
- 2.5dB: 0 - 1.5V
- 6dB: 0 - 2.2V
- 11dB: 0 - 3.6V

### DAC Specifications

| DAC | GPIO | Resolution | Output Range | LSB |
|-----|------|-----------|--------------|-----|
| 1 | 25 | 8-bit | 0 - 3.3V | 12.9 mV |
| 2 | 26 | 8-bit | 0 - 3.3V | 12.9 mV |

### UART Interfaces

| UART | TX | RX | Default Baud | Max Baud | FIFO |
|------|----|----|--------------|----------|------|
| 0 | 1 | 3 | 115200 | 5 Mbps | 128 |
| 1 | 10 | 9 | 115200 | 5 Mbps | 128 |
| 2 | 17 | 16 | 115200 | 5 Mbps | 128 |

### I2C Interfaces

| I2C | SDA | SCL | Default Speed | Max Speed |
|-----|-----|-----|---------------|-----------|
| 0 | 21 | 22 | 100 kHz | 1 MHz |
| 1 | 18 | 19 | 100 kHz | 1 MHz |

### SPI Interfaces

| SPI | CLK | MOSI | MISO | CS | Max Speed | DMA |
|-----|-----|------|------|----|-----------|----|
| 1 | 14 | 13 | 12 | 15 | 80 MHz | 4KB |
| 2 | 18 | 23 | 19 | 5 | 80 MHz | 4KB |
| 3 | 6 | 7 | 8 | 11 | 80 MHz | 4KB |

## Usage Example

### Basic GPIO Operations

```cpp
#include <ESP32.h>

void setup() {
    pinMode(18, OUTPUT);      // Set GPIO18 as output
    pinMode(36, INPUT);       // Set GPIO36 as input (ADC-only)
}

void loop() {
    digitalWrite(18, HIGH);   // Drive GPIO18 high
    delay(500);
    
    int val = digitalRead(36); // Read GPIO36
    delay(500);
    digitalWrite(18, LOW);    // Drive GPIO18 low
    delay(500);
}
```

### ADC Reading (Analog Input)

```cpp
void setup() {
    analogReadResolution(12);              // 12-bit resolution
    analogSetAttenuation(ADC_11db);        // Full range 0-3.6V
}

void loop() {
    uint16_t adc_raw = analogRead(36);     // Read ADC1 CH0
    uint32_t adc_mv = analogReadMilliVolts(36);  // In millivolts
    
    Serial.print("Raw: ");
    Serial.print(adc_raw);
    Serial.print(" mV: ");
    Serial.println(adc_mv);
    
    delay(100);
}
```

### DAC Output (Analog Output)

```cpp
void loop() {
    for (uint8_t val = 0; val < 256; val++) {
        dacWrite(25, val);    // DAC1 on GPIO25: 0-3.3V
        delay(10);
    }
}
```

### PWM / LEDC

```cpp
void setup() {
    ledcSetup(0, 5000, 8);    // Channel 0, 5 kHz, 8-bit
    ledcAttachPin(18, 0);     // Attach GPIO18 to channel 0
}

void loop() {
    for (int duty = 0; duty < 256; duty++) {
        ledcWrite(0, duty);   // 0% to 100% brightness
        delay(10);
    }
}
```

### UART Communication

```cpp
void setup() {
    Serial.begin(115200);     // UART0 at 115200 baud
}

void loop() {
    if (Serial.available()) {
        int c = Serial.read();
        Serial.print("Received: ");
        Serial.println((char)c);
    }
}
```

### I2C Communication

```cpp
void setup() {
    Wire.begin(21, 22, 400000);  // I2C0: SDA=21, SCL=22, 400 kHz
}

void loop() {
    Wire.beginTransmission(0x68);  // Address 0x68
    Wire.write(0x3B);               // Register address
    Wire.endTransmission();
    
    Wire.requestFrom(0x68, 6);      // Read 6 bytes
    while (Wire.available()) {
        int c = Wire.read();
    }
}
```

### Timer Interrupt

```cpp
hw_timer_t * timer = NULL;

void IRAM_ATTR onTimer() {
    // Interrupt handler (called when timer alarm fires)
    digitalWrite(18, !digitalRead(18));
}

void setup() {
    timer = timerBegin(0, 80, true);        // Timer 0, divider=80, count up
    timerAttachInterrupt(timer, &onTimer, true);
    timerAlarmWrite(timer, 1000000, true);  // Alarm every 1M cycles (1s @ 1MHz)
    timerAlarmEnable(timer);
}
```

### Touch Sensor

```cpp
void setup() {
    pinMode(4, INPUT);  // Touch channel 0 on GPIO4
}

void loop() {
    uint16_t touch_val = touchRead(4);
    
    if (touch_val < 400) {
        Serial.println("Touch detected!");
    }
    
    delay(50);
}
```

## Simulation-Specific Features

### Value Injection (Testing)

The `inject()` method allows test code to simulate real-world sensor values:

```cpp
// In Python test code:
mcu_node.inject(
    adc1_ch4_mv=2500,        # Set GPIO32 (ADC1-4) to 2500mV
    touch_ch0_value=300,     # Set touch sensor to 300 (triggered)
    temperature_c=45         # Set chip temp to 45°C
)
```

### Runtime Metrics

Query the MCU state during simulation:

```cpp
float uptime = mcu.get_uptime_ms();        // Milliseconds since boot
float temp = mcu.get_chip_temperature();   // Current chip temperature
int current = mcu.get_supply_current();    // Current in µA
```

### Memory Specifications

- Internal SRAM: 520 KB
- RTC Memory: 8 KB
- Instruction Cache: 16 KB
- Data Cache: 16 KB
- External RAM: None (on this module)
- External Flash: 4 MB (assumed)

## Pin Configurations for Strapping

These GPIO levels at boot determine the ESP32 behavior:

| Pin | Level | Meaning |
|-----|-------|---------|
| GPIO0 | LOW | Normal boot (HIGH = download mode) |
| GPIO2 | LOW | Normal boot (HIGH = reserved) |
| GPIO15 | LOW | Normal boot (HIGH = download mode) |
| GPIO12 | HIGH | Selects flash voltage (low=1.8V, high=3.3V) |

The model initializes these pins to their default values. Firmware can configure pull-ups/pull-downs to override defaults.

## Synchronization with Firmware

The `shim` object (ArduinoShim instance) bridges between firmware API calls and the simulation:

1. **Firmware calls**: `digitalWrite(18, HIGH)` → 
2. **Shim translates**: GPIO number → KiCad net name → 
3. **Bus drives**: Physical net signal in simulation

All pin-to-net mappings are resolved from the KiCad schematic at load time.

## Thermal Simulation

The chip temperature is simulated based on:

- **Base**: 25°C ambient
- **Power dissipation**: VDD × Supply Current × θJA
- **Cooling**: Exponential decay with ~10 second time constant
- **Clamp**: 25°C to 100°C valid range

Supply current is automatically updated based on active peripherals:
- GPIO outputs: +20 mA per pin
- ADC enabled: +5 mA
- DAC enabled: +10 mA
- PWM channels: +5 mA per active channel
- UART enabled: +2 mA per interface
- Timer enabled: +1 mA per timer

## Datasheets Referenced

- ESP32 Datasheet (Espressif)
- ESP32-WROOM-32 Datasheet (Espressif)
- ESP32 Technical Reference Manual (Espressif)

---

**Model Version**: 2.0.0  
**Last Updated**: 2026-06-19  
**Compatibility**: Simulator v1.2.0+  
**Maintainer**: Espressif Systems
