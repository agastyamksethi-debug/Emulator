"""
MPU-6050 6-axis IMU (InvenSense) — I2C device model.

Presents the real register map over the simulator's I2C bus: a firmware that
talks to it the normal way (write the register pointer, then read N
auto-incrementing bytes) gets correct, scaled sensor data.

Physical inputs (set from the GUI or a test):
  set_acceleration(x, y, z)   in g     (default 0, 0, 1 — gravity on +Z)
  set_rotation(x, y, z)       in °/s   (default 0, 0, 0)
  set_temperature(c)          in °C    (default 25)

Output scaling follows the datasheet and honours the configured full-scale
ranges (ACCEL_CONFIG / GYRO_CONFIG):
  accel LSB/g    = 16384 / 8192 / 4096 / 2048   for ±2/4/8/16 g
  gyro  LSB/°/s  = 131 / 65.5 / 32.8 / 16.4      for ±250/500/1000/2000 °/s
  temp  °C       = raw / 340 + 36.53

Note: the C++ firmware bridge doesn't yet expose Wire/I2C, so this device is
driven through the bus I2C API (and the Python ArduinoShim path).  The model
itself is firmware-agnostic.
"""

from __future__ import annotations
import struct
from core.node import Node
from core.fidelity import sensor_noise
import core.registry as registry

# ── register addresses ────────────────────────────────────────────────────────
_SMPLRT_DIV   = 0x19
_CONFIG       = 0x1A
_GYRO_CONFIG  = 0x1B
_ACCEL_CONFIG = 0x1C
_ACCEL_XOUT_H = 0x3B
_TEMP_OUT_H   = 0x41
_GYRO_XOUT_H  = 0x43
_PWR_MGMT_1   = 0x6B
_WHO_AM_I     = 0x75

_ACCEL_LSB = {0: 16384.0, 1: 8192.0, 2: 4096.0, 3: 2048.0}   # per AFS_SEL
_GYRO_LSB  = {0: 131.0, 1: 65.5, 2: 32.8, 3: 16.4}            # per FS_SEL


def _s16(v: float) -> int:
    return max(-32768, min(32767, int(round(v))))


class MPU6050Node(Node):
    PART_ID = "mpu6050"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        self.i2c_address: int = int(descriptor.get("i2c_address", 0x68))

        # stored/config registers
        self._regs = bytearray(128)
        self._ptr  = 0

        # physical inputs
        self._accel = [0.0, 0.0, 1.0]   # g  (gravity on +Z at rest)
        self._gyro  = [0.0, 0.0, 0.0]   # °/s
        self._temp  = 25.0              # °C

        self._init_regs()

    def _init_regs(self):
        self._regs[:] = bytearray(128)
        self._regs[_PWR_MGMT_1]   = 0x40   # sleep bit set on power-up
        self._regs[_WHO_AM_I]     = 0x68
        self._regs[_ACCEL_CONFIG] = 0x00   # ±2 g
        self._regs[_GYRO_CONFIG]  = 0x00   # ±250 °/s
        self._ptr = 0

    # ── physical inputs ─────────────────────────────────────────────────────────

    def set_acceleration(self, x: float, y: float, z: float):
        self._accel = [float(x), float(y), float(z)]

    def set_rotation(self, x: float, y: float, z: float):
        self._gyro = [float(x), float(y), float(z)]

    def set_temperature(self, celsius: float):
        self._temp = float(celsius)

    @property
    def asleep(self) -> bool:
        return bool(self._regs[_PWR_MGMT_1] & 0x40)

    # ── live sensor register block (0x3B … 0x48) ────────────────────────────────

    def _sensor_block(self) -> bytes:
        afs = (self._regs[_ACCEL_CONFIG] >> 3) & 0x03
        fs  = (self._regs[_GYRO_CONFIG]  >> 3) & 0x03
        a_lsb = _ACCEL_LSB[afs]
        g_lsb = _GYRO_LSB[fs]

        ax, ay, az = (_s16(v * a_lsb + sensor_noise(40)) for v in self._accel)
        gx, gy, gz = (_s16(v * g_lsb + sensor_noise(2))  for v in self._gyro)
        temp_raw = _s16((self._temp - 36.53) * 340.0)

        # big-endian, signed: accel(3) temp(1) gyro(3) → 14 bytes from 0x3B
        return struct.pack(">hhhhhhh", ax, ay, az, temp_raw, gx, gy, gz)

    # ── register access ─────────────────────────────────────────────────────────

    def _read_reg(self, reg: int) -> int:
        if _ACCEL_XOUT_H <= reg <= _GYRO_XOUT_H + 5:   # 0x3B … 0x48
            return self._sensor_block()[reg - _ACCEL_XOUT_H]
        return self._regs[reg & 0x7F]

    def _write_reg(self, reg: int, value: int):
        reg &= 0x7F
        if reg == _WHO_AM_I:
            return                      # read-only identity register
        if _ACCEL_XOUT_H <= reg <= _GYRO_XOUT_H + 5:
            return                      # read-only measurement registers
        self._regs[reg] = value & 0xFF

    # ── I2C interface (called by the bus) ───────────────────────────────────────

    def i2c_write(self, address: int, register: int, data: bytes):
        self._ptr = register & 0x7F
        for i, b in enumerate(data or b""):
            self._write_reg((register + i) & 0x7F, b)

    def i2c_read(self, address: int, register: int, length: int) -> bytes:
        start = (register & 0x7F) if register else self._ptr
        out = bytearray(self._read_reg((start + i) & 0x7F) for i in range(length))
        self._ptr = (start + length) & 0x7F
        return bytes(out)

    def reset(self):
        self._init_regs()
        self._accel = [0.0, 0.0, 1.0]
        self._gyro  = [0.0, 0.0, 0.0]
        self._temp  = 25.0


# ── registration ──────────────────────────────────────────────────────────────

registry.register_part("Device:MPU6050",       MPU6050Node, i2c_address=0x68)
registry.register_part("InvenSense:MPU-6050",  MPU6050Node, i2c_address=0x68)
registry.register_part("mpu6050",              MPU6050Node, i2c_address=0x68)
