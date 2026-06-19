"""
SPI bus model.

Devices are differentiated by chip-select (CS) pin number, which is
resolved from the netlist. Only one CS may be asserted at a time.
"""

from __future__ import annotations


class SPIBus:
    def __init__(self, bus_id: int = 0, max_speed_hz: int = 40_000_000):
        self.bus_id = bus_id
        self.max_speed_hz = max_speed_hz
        self._devices: dict[int, object] = {}   # cs_pin -> Node
        self._active_cs: int | None = None

    def attach(self, cs_pin: int, node):
        self._devices[cs_pin] = node

    def assert_cs(self, cs_pin: int):
        self._active_cs = cs_pin
        node = self._devices.get(cs_pin)
        if node:
            node.gpio_write(cs_pin, 0)   # active-low CS

    def deassert_cs(self, cs_pin: int):
        node = self._devices.get(cs_pin)
        if node:
            node.gpio_write(cs_pin, 1)
        self._active_cs = None

    def transfer(self, data: bytes) -> bytes:
        """Full-duplex transfer while CS is asserted."""
        if self._active_cs is None:
            return bytes(len(data))
        node = self._devices.get(self._active_cs)
        if node is None:
            return bytes(len(data))
        return node.spi_transfer(self._active_cs, data)
