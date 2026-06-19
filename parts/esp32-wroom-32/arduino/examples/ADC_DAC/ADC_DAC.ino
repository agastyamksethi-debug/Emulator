/*
 * ADC & DAC Example
 * Demonstrates analog input (ADC) and analog output (DAC) on ESP32
 * 
 * Circuit:
 *   - Analog input connected to GPIO36 (ADC1 Channel 0)
 *   - DAC output on GPIO25 (DAC Channel 0)
 *   - Serial monitoring via UART0
 */

#include <ESP32.h>

const uint8_t ADC_PIN = 36;   // GPIO36 = ADC1CH0 (input-only)
const uint8_t DAC_PIN = 25;   // GPIO25 = DAC_CH0

uint16_t adc_reading = 0;
uint8_t dac_value = 0;

void setup() {
    Serial.begin(115200);
    delay(100);
    
    Serial.println("\n\nESP32 ADC & DAC Example");
    
    // Set ADC resolution to 12-bit (0-4095)
    analogReadResolution(12);
    
    // Set ADC attenuation to 11dB for full range (0-3.6V)
    analogSetAttenuation(ADC_11db);
    
    Serial.println("ADC & DAC initialized");
}

void loop() {
    // Read ADC value from GPIO36 (12-bit, 0-4095)
    adc_reading = analogRead(ADC_PIN);
    
    // Convert ADC reading to millivolts
    uint32_t adc_mv = analogReadMilliVolts(ADC_PIN);
    
    // Convert ADC reading (0-4095) to DAC value (0-255)
    dac_value = (adc_reading >> 4);  // Divide by 16 to scale down
    
    // Write DAC output
    dacWrite(DAC_PIN, dac_value);
    
    // Print results
    Serial.print("ADC Raw: ");
    Serial.print(adc_reading);
    Serial.print(" | ADC mV: ");
    Serial.print(adc_mv);
    Serial.print(" | DAC Value: ");
    Serial.println(dac_value);
    
    delay(500);
}
