"""
Interrupt bus — fires Python callbacks when net edge conditions are met.

Sensors drive their INT pin LOW/HIGH; the MCU calls attachInterrupt() on
the corresponding GPIO; this bus detects the edge each tick and calls back.

Usage (inside ArduinoShim):
    bus.interrupt.attach(net_name, callback, FALLING)

Tick sequence (managed by SimRunner):
    bus.interrupt.snapshot(gpio_bus)   # before nodes tick
    ... nodes tick, physics runs ...
    bus.interrupt.tick(gpio_bus)       # fires any triggered callbacks
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from core.protocols.gpio import GPIOBus

# Interrupt trigger modes — pass as the 'mode' argument to attach()
RISING  = "RISING"   # LOW → HIGH transition
FALLING = "FALLING"  # HIGH → LOW transition
CHANGE  = "CHANGE"   # any transition
LOW     = "LOW"      # fires every tick while net is LOW
HIGH    = "HIGH"     # fires every tick while net is HIGH


@dataclass
class _ISR:
    callback: Callable[[], None]
    mode: str


class InterruptBus:
    def __init__(self):
        self._handlers: dict[str, list[_ISR]] = {}
        self._prev:     dict[str, int] = {}      # last-known digital state per net

    def attach(self, net_name: str, callback: Callable[[], None],
               mode: str = FALLING) -> None:
        """Register an ISR on a named net."""
        if net_name not in self._handlers:
            self._handlers[net_name] = []
            self._prev[net_name] = -1   # -1 = not yet sampled
        self._handlers[net_name].append(_ISR(callback=callback, mode=mode))

    def detach(self, net_name: str) -> None:
        """Remove all ISRs on a net."""
        self._handlers.pop(net_name, None)
        self._prev.pop(net_name, None)

    def snapshot(self, gpio_bus: GPIOBus) -> None:
        """Capture net states before the tick. Call this before nodes run."""
        for net in self._handlers:
            self._prev[net] = gpio_bus.digital(net)

    def tick(self, gpio_bus: GPIOBus) -> None:
        """Compare current state to snapshot and fire any matching ISRs."""
        for net, handlers in self._handlers.items():
            prev = self._prev.get(net, -1)
            curr = gpio_bus.digital(net)
            for isr in handlers:
                fire = False
                m = isr.mode
                if   m == RISING  and prev == 0 and curr == 1: fire = True
                elif m == FALLING and prev == 1 and curr == 0: fire = True
                elif m == CHANGE  and prev not in (-1, curr):  fire = True
                elif m == LOW     and curr == 0:               fire = True
                elif m == HIGH    and curr == 1:               fire = True
                if fire:
                    isr.callback()
            self._prev[net] = curr
