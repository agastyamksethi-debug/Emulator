// MPU-6050 IMU over I2C
//
// Wakes the sensor, then reads the 6 accelerometer bytes each loop and prints
// the raw X/Y/Z counts.  At rest (±2 g range) Z reads ~16384 (1 g).
//
// Wiring:  IO21 → SDA,  IO22 → SCL,  3V3 → VCC,  GND → GND

const int MPU = 0x68;

int16_t read_word() {
  int hi = Wire.read();
  int lo = Wire.read();
  return (int16_t)((hi << 8) | lo);
}

void setup() {
  Serial.begin(115200);
  Wire.begin();

  // wake from sleep (PWR_MGMT_1 = 0)
  Wire.beginTransmission(MPU);
  Wire.write(0x6B);
  Wire.write(0x00);
  Wire.endTransmission(true);

  // WHO_AM_I
  Wire.beginTransmission(MPU);
  Wire.write(0x75);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU, 1);
  Serial.print("WHO_AM_I: 0x");
  Serial.println(Wire.read(), HEX);
}

void loop() {
  Wire.beginTransmission(MPU);
  Wire.write(0x3B);                 // ACCEL_XOUT_H
  Wire.endTransmission(false);
  Wire.requestFrom(MPU, 6);

  int16_t ax = read_word();
  int16_t ay = read_word();
  int16_t az = read_word();

  Serial.print("ax:");  Serial.print(ax);
  Serial.print(" ay:"); Serial.print(ay);
  Serial.print(" az:"); Serial.println(az);

  delay(100);
}
