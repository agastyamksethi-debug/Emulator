"""
I2C bus model.

Handles address arbitration and ACK/NAK semantics. Multiple nodes can
share the same I2C bus; each is addressed by its 7-bit address.
"""


class I2CBus:
    def __init__(self, bus_id: int = 0, speed_hz: int = 400_000):
        self.bus_id = bus_id
        self.speed_hz = speed_hz
        self._devices: dict[int, object] = {}   # address -> Node

    def attach(self, address: int, node):
        if address in self._devices:
            raise ValueError(f"I2C address 0x{address:02X} already in use on bus {self.bus_id}")
        self._devices[address] = node

    def write(self, address: int, register: int, data: bytes) -> bool:
        """Returns True on ACK, False on NAK (device not present)."""
        node = self._devices.get(address)
        if node is None:
            return False
        node.i2c_write(address, register, data)
        return True

    def read(self, address: int, register: int, length: int) -> bytes | None:
        """Returns bytes on ACK, None on NAK."""
        node = self._devices.get(address)
        if node is None:
            return None
        return node.i2c_read(address, register, length)
