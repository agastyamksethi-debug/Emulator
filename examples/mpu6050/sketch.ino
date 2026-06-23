// MPU-6050 6-axis IMU over I2C
//
// Reads the accelerometer, temperature and gyroscope each loop, prints the
// scaled values, and derives pitch/roll from the accelerometer.
//
// Wiring (see circuit.json):
//   IO21 → SDA,  IO22 → SCL  (both pulled up to 3V3 via 4.7k)
//   3V3 → VCC,  GND → GND,  AD0 → GND (address 0x68),  100n decoupling on 3V3
//
// Scaling at the default ranges: accel ±2g → 16384 LSB/g, gyro ±250°/s →
// 131 LSB/(°/s), temp °C = raw/340 + 36.53.

#include <math.h>

const int MPU = 0x68;

int16_t read16() {
  int hi = Wire.read();
  int lo = Wire.read();
  return (int16_t)((hi << 8) | lo);
}

void writeReg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission(true);
}

void setup() {
  Serial.begin(115200);
  Wire.begin();

  Wire.beginTransmission(MPU);
  Wire.write(0x75);                 // WHO_AM_I
  Wire.endTransmission(false);
  Wire.requestFrom(MPU, 1);
  Serial.print("WHO_AM_I: 0x");
  Serial.println(Wire.read(), HEX);

  writeReg(0x6B, 0x00);             // PWR_MGMT_1 = 0 → wake
  writeReg(0x1C, 0x00);             // ACCEL_CONFIG → ±2 g
  writeReg(0x1B, 0x00);             // GYRO_CONFIG  → ±250 °/s
  Serial.println("MPU6050 ready");
}

void loop() {
  // burst-read 14 bytes: accel(6) temp(2) gyro(6) from 0x3B
  Wire.beginTransmission(MPU);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU, 14);

  int16_t ax = read16(), ay = read16(), az = read16();
  int16_t traw = read16();
  int16_t gx = read16(), gy = read16(), gz = read16();

  float gX = ax / 16384.0, gY = ay / 16384.0, gZ = az / 16384.0;
  float pitch = atan2(gX, sqrt(gY * gY + gZ * gZ)) * 57.2958;
  float roll  = atan2(gY, gZ) * 57.2958;
  float tempC = traw / 340.0 + 36.53;

  Serial.print("a[g]:");   Serial.print(gX, 2); Serial.print(",");
  Serial.print(gY, 2);     Serial.print(",");   Serial.print(gZ, 2);
  Serial.print("  g[dps]:"); Serial.print(gx / 131.0, 1); Serial.print(",");
  Serial.print(gy / 131.0, 1); Serial.print(",");        Serial.print(gz / 131.0, 1);
  Serial.print("  pitch:"); Serial.print(pitch, 1);
  Serial.print("  roll:");  Serial.print(roll, 1);
  Serial.print("  T:");     Serial.print(tempC, 1);
  Serial.println();

  delay(200);
}
