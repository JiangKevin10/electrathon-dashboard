#include <SoftwareSerial.h>
#include <TinyGPS++.h>

const int hallPin = 2;
const int buttonPin = 4;
const int ledPin = 7;
const int gpsRxPin = 10;
const int gpsTxPin = 11;

const unsigned long debounceDelay = 50;
const unsigned long dashboardSendInterval = 100;
const unsigned long gpsNoFixReportInterval = 2000;

SoftwareSerial gpsSerial(gpsRxPin, gpsTxPin);
TinyGPSPlus gps;

volatile unsigned long count = 0;

bool loggingState = false;

bool lastButtonReading = HIGH;
bool stableButtonState = HIGH;

unsigned long lastDebounceTime = 0;

void sendGpsState() {
  if (!gps.location.isValid()) {
    Serial.println("GPS:NOFIX");
    return;
  }

  Serial.print("GPS:");
  Serial.print(gps.location.lat(), 6);
  Serial.print(",");
  Serial.print(gps.location.lng(), 6);
  Serial.print(",");
  Serial.println(gps.satellites.isValid() ? gps.satellites.value() : 0);
}

void sendGpsTimeState() {
  if (!gps.date.isValid() || !gps.time.isValid()) {
    Serial.println("GPSTIME:NOFIX");
    return;
  }

  Serial.print("GPSTIME:");
  Serial.print(gps.date.year());
  Serial.print("-");
  if (gps.date.month() < 10) {
    Serial.print("0");
  }
  Serial.print(gps.date.month());
  Serial.print("-");
  if (gps.date.day() < 10) {
    Serial.print("0");
  }
  Serial.print(gps.date.day());
  Serial.print(",");
  if (gps.time.hour() < 10) {
    Serial.print("0");
  }
  Serial.print(gps.time.hour());
  Serial.print(":");
  if (gps.time.minute() < 10) {
    Serial.print("0");
  }
  Serial.print(gps.time.minute());
  Serial.print(":");
  if (gps.time.second() < 10) {
    Serial.print("0");
  }
  Serial.println(gps.time.second());
}

void hallISR() {
  count++;
}

void setup() {
  Serial.begin(9600);
  gpsSerial.begin(9600);

  pinMode(hallPin, INPUT_PULLUP);
  pinMode(buttonPin, INPUT_PULLUP);
  pinMode(ledPin, OUTPUT);

  attachInterrupt(digitalPinToInterrupt(hallPin), hallISR, FALLING);

  digitalWrite(ledPin, LOW);
}

void loop() {
  while (gpsSerial.available() > 0) {
    gps.encode(gpsSerial.read());
  }

  bool reading = digitalRead(buttonPin);

  if (reading != lastButtonReading) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (reading != stableButtonState) {
      stableButtonState = reading;

      if (stableButtonState == LOW) {
        loggingState = !loggingState;
        digitalWrite(ledPin, loggingState ? HIGH : LOW);
      }
    }
  }

  lastButtonReading = reading;

  static unsigned long lastDashboardSendTime = 0;
  static unsigned long lastGpsNoFixReportTime = 0;
  const unsigned long now = millis();

  if (now - lastDashboardSendTime >= dashboardSendInterval) {
    Serial.print("COUNT:");
    Serial.println(count);

    Serial.print("LOG:");
    Serial.println(loggingState ? 1 : 0);

    lastDashboardSendTime = now;
  }

  if (gps.location.isUpdated()) {
    sendGpsState();
  } else if (!gps.location.isValid() && now - lastGpsNoFixReportTime >= gpsNoFixReportInterval) {
    Serial.println("GPS:NOFIX");
    lastGpsNoFixReportTime = now;
  }

  if (gps.date.isUpdated() || gps.time.isUpdated()) {
    sendGpsTimeState();
  } else if ((!gps.date.isValid() || !gps.time.isValid()) && now - lastGpsNoFixReportTime >= gpsNoFixReportInterval) {
    Serial.println("GPSTIME:NOFIX");
  }
}
