// Potentiometer → LED brightness → Photoresistor feedback
//
// Turn POT1 (knob on the Real-World canvas) to set the LED brightness.
// The LED (D1) illuminates the photoresistor (LDR1); its analog reading
// rises and falls with the LED brightness and is printed to the monitor.
//
// NOTE: draw a light wire from D1's LIGHT port to LDR1's LIGHT IN port on
// the Real-World canvas — the LDR reads dark until that optical link exists.
//
// Wiring:
//   IO34 → POT1 wiper      (analog in : 0..4095)
//   IO2  → LEDC PWM → 220Ω → D1 → GND   (LED brightness)
//   IO35 → LDR1 divider out (analog in : rises with light)

const int POT_PIN = 34;
const int LDR_PIN = 35;
const int LED_PIN = 2;

const int LEDC_CH   = 0;
const int LEDC_FREQ = 5000;
const int LEDC_RES  = 8;       // 8-bit duty: 0..255

void setup() {
  Serial.begin(115200);
  ledcSetup(LEDC_CH, LEDC_FREQ, LEDC_RES);
  ledcAttachPin(LED_PIN, LEDC_CH);
  Serial.println("pot/led/ldr demo ready");
}

void loop() {
  int pot  = analogRead(POT_PIN);          // 0..4095
  int duty = pot * 255 / 4095;             // 0..255
  ledcWrite(LEDC_CH, duty);

  int ldr = analogRead(LDR_PIN);           // rises with LED brightness

  Serial.print("pot:");
  Serial.print(pot);
  Serial.print("  duty:");
  Serial.print(duty);
  Serial.print("  ldr:");
  Serial.println(ldr);

  delay(10);
}
