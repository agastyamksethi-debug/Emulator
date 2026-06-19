"""
Base class for every simulated component — MCUs, ICs, passives, all of them.

Subclass this and override only the protocol methods your part uses.
The bus calls tick() every simulation step and routes protocol traffic
to the matching method based on the netlist topology.
"""

from __future__ import annotations


class Node:
    def __init__(self, instance_id: str, descriptor: dict):
        self.id = instance_id
        self.descriptor = descriptor

        # Physics state — updated by physics/engine.py each tick
        self.temperature: float = 25.0       # °C, starts at ambient
        self.power_dissipation: float = 0.0  # W, set by the node each tick

    def reset(self):
        """Called on power-on or explicit reset signal."""
        pass

    def tick(self, dt_ms: float):
        """Advance internal state by dt_ms milliseconds."""
        pass

    # ---------------------------------------------------------------- SPI -----
    def spi_transfer(self, cs_pin: int, data: bytes) -> bytes:
        """Full-duplex SPI exchange. cs_pin identifies which CS line was asserted."""
        return bytes(len(data))

    # ---------------------------------------------------------------- I2C -----
    def i2c_write(self, address: int, register: int, data: bytes):
        """I2C write to register at address."""
        pass

    def i2c_read(self, address: int, register: int, length: int) -> bytes:
        """I2C read from register at address, return length bytes."""
        return bytes(length)

    # -------------------------------------------------------------- GPIO -----
    def gpio_write(self, pin: int, value: int):
        """Drive a GPIO pin HIGH (1) or LOW (0)."""
        pass

    def gpio_read(self, pin: int) -> int:
        """Sample a GPIO pin. Returns 0 or 1."""
        return 0

    # ------------------------------------------------------------- UART -----
    def uart_write(self, port: int, data: bytes):
        """Transmit bytes on UART port."""
        pass

    def uart_read(self, port: int, length: int) -> bytes:
        """Receive up to length bytes from UART port."""
        return b""

    def __repr__(self):
        return f"<Node {self.id} ({self.descriptor.get('part', '?')})>"
