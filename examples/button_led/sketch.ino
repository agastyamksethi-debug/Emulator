// Button + LED test
// Hold the button (SW1) → LED (D1) turns on
// Release → LED turns off
//
// Wiring:
//   GPIO4  → button → GND   (INPUT_PULLUP: HIGH when open, LOW when pressed)
//   GPIO2  → 220Ω   → LED → GND

const int BTN_PIN = 4;
const int LED_PIN = 2;

int ledState = 0;
int lastBtn  = 1;

void setup() {
  pinMode(BTN_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
}

void loop() {
  int btn = digitalRead(BTN_PIN);

  if (lastBtn == 1 && btn == 0) {
      ledState = !ledState;
      digitalWrite(LED_PIN, ledState ? HIGH : LOW);
      Serial.println(ledState? "ON" : "OFF");
  }

  lastBtn = btn;
  delay(20);
}