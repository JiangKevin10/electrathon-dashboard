#include <Arduino.h>
#include <TinyGPS++.h>

// Simple GPS test. GPS TX -> ESP32 GPIO17
// Open Serial Monitor at 115200 baud.

HardwareSerial gpsSerial(2);
TinyGPSPlus gps;

const uint8_t gpsRxPin = 17;
const uint8_t gpsTxPin = 16;

unsigned long bytesReceived = 0;
unsigned long lastPrint = 0;

void setup() {
  Serial.begin(115200);
  gpsSerial.begin(9600, SERIAL_8N1, gpsRxPin, gpsTxPin);
  delay(500);
  Serial.println("=== GPS Test ===");
  Serial.println("GPS TX -> GPIO17  |  115200 baud monitor  |  Updates every 2s");
  Serial.println();
}

void loop() {
  while (gpsSerial.available() > 0) {
    char c = (char)gpsSerial.read();
    gps.encode(c);
    bytesReceived++;
  }

  unsigned long now = millis();
  if (now - lastPrint < 2000) return;
  lastPrint = now;

  Serial.println("--------------------------------");

  // Bytes check
  Serial.print("Bytes received : ");
  Serial.println(bytesReceived);
  if (bytesReceived == 0) {
    Serial.println(">>> NO DATA - check GPS power and TX->GPIO17 wire <<<");
    Serial.println();
    return;
  }

  // Fix status
  bool hasFix = gps.location.isValid();
  Serial.print("Fix            : ");
  Serial.println(hasFix ? "YES" : "NO (waiting...)");

  // Satellites
  Serial.print("Satellites     : ");
  if (gps.satellites.isValid()) {
    Serial.println(gps.satellites.value());
  } else {
    Serial.println("--");
  }

  // Position
  if (hasFix) {
    Serial.print("Latitude       : ");
    Serial.println(gps.location.lat(), 6);
    Serial.print("Longitude      : ");
    Serial.println(gps.location.lng(), 6);
    Serial.print("Speed (km/h)   : ");
    Serial.println(gps.speed.isValid() ? gps.speed.kmph() : 0, 1);
  }

  // Time
  if (gps.time.isValid() && gps.date.isValid()) {
    char buf[32];
    snprintf(buf, sizeof(buf), "%04d-%02d-%02d  %02d:%02d:%02d UTC",
      gps.date.year(), gps.date.month(), gps.date.day(),
      gps.time.hour(), gps.time.minute(), gps.time.second());
    Serial.print("Time           : ");
    Serial.println(buf);
  } else {
    Serial.println("Time           : --");
  }

  Serial.println();
}
