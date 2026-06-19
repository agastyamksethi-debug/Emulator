/*
 * PWM / LEDC Example
 * Demonstrates LED brightness control using PWM on ESP32
 * 
 * Circuit:
 *   - LED connected to GPIO18 with 220Ω resistor to GND
 *   - Serial monitoring via UART0
 */

#include <ESP32.h>

const uint8_t LED_PIN = 18;
const uint8_t LEDC_CHANNEL = 0;

// PWM parameters
const uint32_t PWM_FREQUENCY = 5000;      // 5 kHz
const uint8_t PWM_RESOLUTION = 8;         // 8-bit (0-255)

void setup() {
    Serial.begin(115200);
    delay(100);
    
    Serial.println("\n\nESP32 PWM/LEDC Example");
    
    // Setup LEDC channel with frequency and resolution
    ledcSetup(LEDC_CHANNEL, PWM_FREQUENCY, PWM_RESOLUTION);
    
    // Attach GPIO to LEDC channel
    ledcAttachPin(LED_PIN, LEDC_CHANNEL);
    
    Serial.print("LEDC Channel: ");
    Serial.print(LEDC_CHANNEL);
    Serial.print(" | Frequency: ");
    Serial.print(PWM_FREQUENCY);
    Serial.print(" Hz | Resolution: ");
    Serial.print(PWM_RESOLUTION);
    Serial.println(" bit");
}

void loop() {
    // Gradually increase brightness (0 to 255)
    for (uint16_t duty = 0; duty < 256; duty++) {
        ledcWrite(LEDC_CHANNEL, duty);
        Serial.print("Brightness: ");
        Serial.print((duty * 100) / 255);
        Serial.println("%");
        delay(10);
    }
    
    // Gradually decrease brightness (255 to 0)
    for (int16_t duty = 255; duty >= 0; duty--) {
        ledcWrite(LEDC_CHANNEL, duty);
        Serial.print("Brightness: ");
        Serial.print((duty * 100) / 255);
        Serial.println("%");
        delay(10);
    }
    
    delay(500);
}
