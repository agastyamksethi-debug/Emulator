// Standard Arduino blink — no changes needed to run in the simulator.
// GPIO 2 is wired to the LED in the Python runner script.

#define LED_PIN 2

void setup() {
    Serial.begin(115200);
    Serial.println("Blink starting!");
    pinMode(LED_PIN, OUTPUT);
}

void loop() {
    digitalWrite(LED_PIN, HIGH);
    Serial.print("LED ON  t=");
    Serial.println(millis());
    delay(500);

    digitalWrite(LED_PIN, LOW);
    Serial.print("LED OFF t=");
    Serial.println(millis());
    delay(500);
}
