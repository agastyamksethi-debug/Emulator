"""
Waveform recorder — opt-in net voltage sampling over simulation time.

Usage:
    runner.probe("NET_SDA")
    runner.probe("NET_SCL", label="SCL")
    runner.run(100)
    data = runner.waveform("NET_SDA")   # [(time_ms, voltage), ...]
    runner.recorder.export_csv("trace.csv")
"""

from __future__ import annotations  # noqa: F401 — needed for Python 3.9
import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.protocols.gpio import GPIOBus


@dataclass
class WaveformChannel:
    net_name: str
    label:    str
    times_ms: list[float] = field(default_factory=list)
    voltages: list[float] = field(default_factory=list)

    def record(self, time_ms: float, voltage: float) -> None:
        self.times_ms.append(time_ms)
        self.voltages.append(voltage)

    def samples(self) -> list[tuple[float, float]]:
        return list(zip(self.times_ms, self.voltages))

    def clear(self) -> None:
        self.times_ms.clear()
        self.voltages.clear()

    def digital_edges(self, v_threshold: float = 1.65) -> list[tuple[float, int]]:
        """Return (time_ms, 0|1) list — useful for protocol decoding."""
        result: list[tuple[float, int]] = []
        prev = -1
        for t, v in zip(self.times_ms, self.voltages):
            d = 1 if v >= v_threshold else 0
            if d != prev:
                result.append((t, d))
                prev = d
        return result


class WaveformRecorder:
    def __init__(self):
        self._channels: dict[str, WaveformChannel] = {}

    def probe(self, net_name: str, label: str | None = None) -> WaveformChannel:
        """Start recording a net. Idempotent — safe to call multiple times."""
        if net_name not in self._channels:
            self._channels[net_name] = WaveformChannel(
                net_name=net_name,
                label=label or net_name,
            )
        return self._channels[net_name]

    def unprobe(self, net_name: str) -> None:
        self._channels.pop(net_name, None)

    def record(self, time_ms: float, gpio_bus: GPIOBus) -> None:
        """Sample every probed net. Called automatically by SimRunner.tick()."""
        for net_name, channel in self._channels.items():
            channel.record(time_ms, gpio_bus.voltage(net_name))

    def waveform(self, net_name: str) -> list[tuple[float, float]]:
        """Returns [(time_ms, voltage), ...] for the named net."""
        ch = self._channels.get(net_name)
        return ch.samples() if ch else []

    def channel(self, net_name: str) -> WaveformChannel | None:
        return self._channels.get(net_name)

    def clear(self) -> None:
        """Erase all recorded samples (keep probe registrations)."""
        for ch in self._channels.values():
            ch.clear()

    def to_dict(self) -> dict[str, list[tuple[float, float]]]:
        return {name: ch.samples() for name, ch in self._channels.items()}

    def export_csv(self, path: str | Path) -> None:
        """
        Export all channels to CSV.
        Columns: time_ms, <label1>, <label2>, ...
        All channels must have the same number of samples.
        """
        if not self._channels:
            return
        path = Path(path)
        first = next(iter(self._channels.values()))
        times = first.times_ms
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["time_ms"] + [ch.label for ch in self._channels.values()])
            for row in zip(times, *[ch.voltages for ch in self._channels.values()]):
                writer.writerow(row)

    @property
    def channels(self) -> list[str]:
        return list(self._channels.keys())

    def __len__(self) -> int:
        return len(self._channels)

    def __repr__(self):
        return f"<WaveformRecorder  channels={self.channels}>"
