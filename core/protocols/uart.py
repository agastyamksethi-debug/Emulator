"""
UART bus model.

UART is point-to-point — each port is a pair (TX node, RX node).
The bus holds a set of named UART links resolved from the netlist.
Bytes written to TX are buffered and available on the paired RX.
"""

from __future__ import annotations
from collections import deque


class UARTLink:
    """One directional UART channel (TX → RX)."""

    def __init__(self, name: str, baud: int = 115200):
        self.name = name
        self.baud = baud
        self._buf: deque[int] = deque()

    def send(self, data: bytes):
        self._buf.extend(data)

    def receive(self, length: int) -> bytes:
        out = []
        for _ in range(min(length, len(self._buf))):
            out.append(self._buf.popleft())
        return bytes(out)

    def available(self) -> int:
        return len(self._buf)

    def flush(self):
        self._buf.clear()


class UARTPort:
    """
    A bidirectional UART port — owns one TX link and listens on one RX link.
    Two nodes are connected by crossing their TX/RX links.
    """

    def __init__(self, port_id: str, baud: int = 115200):
        self.port_id = port_id
        self.baud = baud
        self._tx: UARTLink | None = None
        self._rx: UARTLink | None = None

    def _set_links(self, tx: UARTLink, rx: UARTLink):
        self._tx = tx
        self._rx = rx

    def write(self, data: bytes):
        if self._tx:
            self._tx.send(data)

    def read(self, length: int) -> bytes:
        if self._rx:
            return self._rx.receive(length)
        return b""

    def available(self) -> int:
        return self._rx.available() if self._rx else 0


class UARTBus:
    """
    Manages all UART connections in the simulation.

    connect(node_a_id, port_a, node_b_id, port_b, baud) wires two ports
    together so that A's TX feeds B's RX and vice versa.
    """

    def __init__(self):
        self._ports: dict[tuple[str, int], UARTPort] = {}   # (node_id, port) → UARTPort
        self._links: list[tuple[UARTLink, UARTLink]] = []

    def port(self, node_id: str, port_num: int = 0, baud: int = 115200) -> UARTPort:
        key = (node_id, port_num)
        if key not in self._ports:
            self._ports[key] = UARTPort(f"{node_id}:UART{port_num}", baud)
        return self._ports[key]

    def connect(self, node_a: str, port_a: int,
                node_b: str, port_b: int, baud: int = 115200):
        """Wire UART ports between two nodes (bidirectional)."""
        link_ab = UARTLink(f"{node_a}→{node_b}", baud)
        link_ba = UARTLink(f"{node_b}→{node_a}", baud)

        pa = self.port(node_a, port_a, baud)
        pb = self.port(node_b, port_b, baud)

        pa._set_links(tx=link_ab, rx=link_ba)
        pb._set_links(tx=link_ba, rx=link_ab)

        self._links.append((link_ab, link_ba))

    def write(self, node_id: str, port_num: int, data: bytes):
        self.port(node_id, port_num).write(data)

    def read(self, node_id: str, port_num: int, length: int) -> bytes:
        return self.port(node_id, port_num).read(length)

    def available(self, node_id: str, port_num: int) -> int:
        return self.port(node_id, port_num).available()
