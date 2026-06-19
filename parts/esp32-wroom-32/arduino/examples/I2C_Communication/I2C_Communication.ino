/*
 * I2C Communication Example
 * Demonstrates I2C communication with a sensor (MPU-6050 IMU simulated)
 * 
 * Circuit:
 *   - SCL: GPIO22 → Device SCL
 *   - SDA: GPIO21 → Device SDA
 *   - +3.3V → Device VCC
 *   - GND → Device GND
 * 
 * Note: This example shows the I2C protocol usage.
 *       A real sensor simulation would provide actual measurement data.
 */

#include <ESP32.h>

// I2C addresses and registers (example: MPU-6050)
#define MPU6050_ADDR        0x68
#define MPU6050_WHOAMI_REG  0x75
#define MPU6050_CONFIG_REG  0x1A
#define MPU6050_ACCEL_XOUT  0x3B

const uint8_t I2C_SDA = 21;
const uint8_t I2C_SCL = 22;

void setup() {
    Serial.begin(115200);
    delay(100);
    
    Serial.println("\n\nESP32 I2C Communication Example");
    
    // Initialize I2C bus
    // Wire.begin(SDA_pin, SCL_pin, frequency)
    Wire.begin(I2C_SDA, I2C_SCL, 400000);  // I2C0, 400 kHz (Fast mode)
    
    Serial.println("I2C Bus initialized");
    Serial.print("SDA: GPIO");
    Serial.print(I2C_SDA);
    Serial.print(", SCL: GPIO");
    Serial.println(I2C_SCL);
    
    // Scan I2C bus for devices
    scanI2CBus();
    
    // Read WHO_AM_I register from MPU-6050
    delay(100);
    readWhoAmI();
}

void loop() {
    // Read accelerometer data
    readAccelerometerData();
    delay(500);
}

void scanI2CBus() {
    Serial.println("\nScanning I2C bus...");
    
    uint8_t device_count = 0;
    
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            Serial.print("  Device found at 0x");
            if (addr < 16) Serial.print("0");
            Serial.println(addr, HEX);
            device_count++;
        }
    }
    
    Serial.print("Total devices found: ");
    Serial.println(device_count);
}

void readWhoAmI() {
    Serial.println("\nReading WHO_AM_I register...");
    
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(MPU6050_WHOAMI_REG);  // Register address
    Wire.endTransmission();
    
    // Request 1 byte from device
    Wire.requestFrom(MPU6050_ADDR, 1);
    
    if (Wire.available()) {
        uint8_t whoami = Wire.read();
        Serial.print("WHO_AM_I: 0x");
        Serial.println(whoami, HEX);
    } else {
        Serial.println("No response from device");
    }
}

void readAccelerometerData() {
    // Request accelerometer data (6 bytes: X, Y, Z high and low)
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(MPU6050_ACCEL_XOUT);  // Starting register
    Wire.endTransmission();
    
    // Read 6 bytes
    Wire.requestFrom(MPU6050_ADDR, 6);
    
    int16_t accel_x = 0, accel_y = 0, accel_z = 0;
    
    if (Wire.available() >= 6) {
        // Accel X
        accel_x = (int16_t)Wire.read() << 8;
        accel_x |= Wire.read();
        
        // Accel Y
        accel_y = (int16_t)Wire.read() << 8;
        accel_y |= Wire.read();
        
        // Accel Z
        accel_z = (int16_t)Wire.read() << 8;
        accel_z |= Wire.read();
        
        // Convert to g (1g = 16384 LSB at ±2g range)
        float ax = (float)accel_x / 16384.0;
        float ay = (float)accel_y / 16384.0;
        float az = (float)accel_z / 16384.0;
        
        Serial.print("Accel (g): X=");
        Serial.print(ax, 3);
        Serial.print(" Y=");
        Serial.print(ay, 3);
        Serial.print(" Z=");
        Serial.println(az, 3);
    }
}
