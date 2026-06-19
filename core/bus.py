"""
Simulation bus — the central coordinator for all simulation traffic.

After parsing a schematic:
  bus = SimBus()
  bus.load_netlist(netlist)      # wires up GPIO nets, SPI CS routing, I2C
  bus.register(node)             # add each IC node
  bus.tick_all(dt_ms)            # advance all nodes one step
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.node import Node
    from core.netlist import NetList

from core.protocols.gpio import GPIOBus
from core.protocols.i2c import I2CBus
from core.protocols.spi import SPIBus
from core.protocols.uart import UARTBus
from core.protocols.interrupt import InterruptBus
import core.registry as registry


class SimBus:
    def __init__(self, v_supply: float = 3.3):
        self.v_supply = v_supply
        self.gpio      = GPIOBus(v_supply=v_supply)
        self.spi       = SPIBus()
        self.i2c       = I2CBus()
        self.uart      = UARTBus()
        self.interrupt = InterruptBus()

        self._nodes: dict[str, Node] = {}
        self._netlist: NetList | None = None

        # net_name → GPIO pin number on the MCU (resolved from netlist)
        self._cs_nets: dict[str, int] = {}

    # ---------------------------------------------------------------- setup ---

    def load_netlist(self, netlist: NetList):
        """
        Populate net voltage slots and build SPI/I2C routing tables.

        For each non-passive IC component:
          - Find its CS pin net → map to a virtual CS pin number
          - Find its I2C address from the registry → attach to I2C bus
        """
        self._netlist = netlist

        # 1. Create GPIO net entries for every net in the schematic
        self.gpio.load_from_netlist(netlist)

        # 2. Drive power rails at their nominal voltages
        for net_name in netlist.nets:
            n = net_name.upper()
            if n in ("VCC", "VDD", "3V3", "+3V3", "3.3V", "VDDI"):
                self.gpio.drive(net_name, "_pwr", self.v_supply)
            elif n in ("5V", "+5V", "VUSB"):
                self.gpio.drive(net_name, "_pwr", 5.0)
            elif n in ("GND", "AGND", "DGND", "PGND", "VSS"):
                self.gpio.drive(net_name, "_pwr", 0.0)

        # 3. Build CS routing: assign a virtual pin number to each unique CS net
        cs_pin_counter = 0
        for ref, comp in netlist.components.items():
            lib_id = comp.get("part", "")
            cat = registry.category_of(ref)

            if cat in registry.PASSIVE_CATEGORIES or cat in registry.INERT_CATEGORIES:
                continue

            cs_pin_name = registry.spi_cs_pin(lib_id)   # usually "CS"
            cs_net = comp["pins"].get(cs_pin_name)
            if cs_net and cs_net not in self._cs_nets:
                self._cs_nets[cs_net] = cs_pin_counter
                cs_pin_counter += 1

        # 4. I2C address routing is deferred until nodes are registered,
        #    because the address comes from the Node instance (or its descriptor).

    def register(self, node: Node):
        """
        Add a simulated IC node to the bus.
        If the node has an i2c_address attribute it is attached to the I2C bus.
        """
        self._nodes[node.id] = node

        # Auto-attach to I2C bus if the node declares an address
        addr = getattr(node, "i2c_address", None)
        if addr is not None:
            try:
                self.i2c.attach(addr, node)
            except ValueError:
                pass    # address conflict — caller must resolve

        # Auto-attach to SPI bus if the node has a CS net wired in the netlist
        if self._netlist:
            comp = self._netlist.components.get(node.id, {})
            lib_id = comp.get("part", "")
            cs_pin_name = registry.spi_cs_pin(lib_id)
            cs_net = comp.get("pins", {}).get(cs_pin_name)
            if cs_net and cs_net in self._cs_nets:
                cs_pin = self._cs_nets[cs_net]
                self.spi.attach(cs_pin, node)

    # ---------------------------------------------------------------- SPI -----

    def spi_assert_cs(self, cs_pin: int):
        self.spi.assert_cs(cs_pin)

    def spi_deassert_cs(self, cs_pin: int):
        self.spi.deassert_cs(cs_pin)

    def spi_transfer(self, data: bytes) -> bytes:
        return self.spi.transfer(data)

    # ---------------------------------------------------------------- I2C -----

    def i2c_write(self, address: int, register: int, data: bytes) -> bool:
        return self.i2c.write(address, register, data)

    def i2c_read(self, address: int, register: int, length: int) -> bytes:
        return self.i2c.read(address, register, length) or bytes(length)

    # -------------------------------------------------------------- GPIO -----

    def drive(self, net_name: str, node_id: str, voltage: float):
        self.gpio.drive(net_name, node_id, voltage)

    def drive_digital(self, net_name: str, node_id: str, high: bool):
        self.gpio.drive_digital(net_name, node_id, high)

    def read_voltage(self, net_name: str) -> float:
        return self.gpio.voltage(net_name)

    def read_digital(self, net_name: str) -> int:
        return self.gpio.digital(net_name)

    # ------------------------------------------------------------- UART -----

    def uart_connect(self, node_a: str, port_a: int,
                     node_b: str, port_b: int, baud: int = 115200):
        self.uart.connect(node_a, port_a, node_b, port_b, baud)

    def uart_write(self, node_id: str, port: int, data: bytes):
        self.uart.write(node_id, port, data)

    def uart_read(self, node_id: str, port: int, length: int) -> bytes:
        return self.uart.read(node_id, port, length)

    # --------------------------------------------------------------- tick ----

    def tick_all(self, dt_ms: float):
        for node in self._nodes.values():
            node.tick(dt_ms)

    # ---------------------------------------------------------------- info ----

    def cs_pin_for_net(self, net_name: str) -> int | None:
        return self._cs_nets.get(net_name)

    def __repr__(self):
        return (f"<SimBus  nodes={list(self._nodes.keys())}  "
                f"nets={len(self.gpio._nets)}  "
                f"cs_routes={len(self._cs_nets)}>")
