#include <Servo.h>
#include <ArduinoJson.h>

Servo servos[5];
int servoPins[5] = { 9, 10, 11, 12, 6 };  // Pins in the arduino board (avoid 13, has onboard LED)
int angle = 180;                            // Default position
int numServos = sizeof(servoPins) / sizeof(servoPins[0]);

void setup() {
  Serial.begin(9600);  // Start serial communication

  for (int i = 0; i < numServos; i++) {
    servos[i].attach(servoPins[i], 500, 2500);  // SG90 pulse range
    servos[i].write(angle);
  }

  Serial.println("Arduino is ready");
}

void loop() {
  if (Serial.available()) {
    String input = Serial.readStringUntil('\n');
    input.trim();

    if (input.length() > 0) {
      Serial.println(input);

      StaticJsonDocument<256> doc;
      DeserializationError error = deserializeJson(doc, input);

      if (error) {
        Serial.print("JSON error: ");
        Serial.println(error.f_str());
        return;
      }

      JsonArray arr = doc.as<JsonArray>();

      for (int i = 0; i < numServos && i < arr.size(); i++) {
        int angle = arr[i];
        servos[i].write(angle);
      }
    }
  }
}