/*
 * Interrupt & Timer Example
 * Demonstrates GPIO interrupt handling and timer-based interrupts on ESP32
 * 
 * Circuit:
 *   - Button connected to GPIO4 with pull-up to 3.3V, active low to GND
 *   - LED connected to GPIO18 with 220Ω resistor to GND
 * 
 * Behavior:
 *   - Timer interrupt toggles LED every 1 second
 *   - Button interrupt toggles LED immediately
 */

#include <ESP32.h>

const uint8_t BUTTON_PIN = 4;
const uint8_t LED_PIN = 18;

volatile uint32_t button_presses = 0;
volatile uint32_t timer_interrupts = 0;
hw_timer_t * timer = NULL;

// GPIO Interrupt handler
void IRAM_ATTR buttonISR() {
    button_presses++;
    // Toggle LED when button is pressed
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
}

// Timer Interrupt handler
void IRAM_ATTR timerISR() {
    timer_interrupts++;
    // Toggle LED every 1 second
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
}

void setup() {
    Serial.begin(115200);
    delay(100);
    
    Serial.println("\n\nESP32 Interrupt & Timer Example");
    
    // Setup GPIO
    pinMode(BUTTON_PIN, INPUT_PULLUP);
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);
    
    // Attach GPIO interrupt
    attachInterrupt(BUTTON_PIN, buttonISR, FALLING);
    
    Serial.print("Button GPIO: ");
    Serial.println(BUTTON_PIN);
    
    // Setup Timer
    // Timer 0, divider = 80 (80 MHz / 80 = 1 MHz), count up
    timer = timerBegin(0, 80, true);
    
    // Attach timer interrupt
    timerAttachInterrupt(timer, &timerISR, true);
    
    // Set timer alarm to 1,000,000 cycles (1 second @ 1 MHz)
    timerAlarmWrite(timer, 1000000, true);  // autoreload = true
    
    // Enable the alarm
    timerAlarmEnable(timer);
    
    Serial.println("Interrupts enabled");
}

void loop() {
    // Report statistics every 5 seconds
    static uint32_t last_report = 0;
    
    if (millis() - last_report >= 5000) {
        last_report = millis();
        
        Serial.print("Uptime: ");
        Serial.print(millis());
        Serial.print(" ms | Button presses: ");
        Serial.print(button_presses);
        Serial.print(" | Timer interrupts: ");
        Serial.println(timer_interrupts);
    }
    
    delay(100);
}
