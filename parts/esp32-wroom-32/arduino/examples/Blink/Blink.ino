/*
 * Blink Example
 * Demonstrates GPIO digital output on ESP32
 * 
 * Circuit: LED connected to GPIO18 with 220Ω resistor to GND
 */

#include <ESP32.h>

const uint8_t LED_PIN = 18;

void setup() {
    // Initialize UART for serial output
    Serial.begin(115200);
    delay(100);
    
    Serial.println("\n\nESP32 Blink Example Starting...");
    
    // Set LED pin as output
    pinMode(LED_PIN, OUTPUT);
    
    Serial.print("LED Pin: ");
    Serial.println(LED_PIN);
}

void loop() {
    // Turn LED on
    digitalWrite(LED_PIN, HIGH);
    Serial.println("LED ON");
    delay(500);
    
    // Turn LED off
    digitalWrite(LED_PIN, LOW);
    Serial.println("LED OFF");
    delay(500);
}
