// MPU-6050 — interrupt-driven read
//
// Enables the data-ready interrupt; the MPU pulses its INT pin each new sample,
// which fires an ISR on IO19.  The loop reads the accelerometer only when the
// ISR flags fresh data — no polling.
//
// Wiring: IO21→SDA, IO22→SCL (4.7k pull-ups), IO19→INT, AD0→GND, 100n decoupling.

const int MPU     = 0x68;
const int INT_PIN = 19;

volatile bool dataReady = false;
volatile int  isrCount  = 0;

void IRAM_ATTR onData() {
  dataReady = true;
  isrCount++;
}

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
  pinMode(INT_PIN, INPUT);

  writeReg(0x6B, 0x00);     // wake
  writeReg(0x38, 0x01);     // INT_ENABLE: DATA_RDY_EN
  attachInterrupt(digitalPinToInterrupt(INT_PIN), onData, RISING);
  Serial.println("MPU interrupt demo ready");
}

void loop() {
  if (dataReady) {
    dataReady = false;
    Wire.beginTransmission(MPU);
    Wire.write(0x3B);
    Wire.endTransmission(false);
    Wire.requestFrom(MPU, 6);
    int16_t ax = read16(), ay = read16(), az = read16();
    Serial.print("INT #");  Serial.print(isrCount);
    Serial.print("  ax:");  Serial.print(ax);
    Serial.print(" ay:");   Serial.print(ay);
    Serial.print(" az:");   Serial.println(az);
  }
  delay(50);
}
