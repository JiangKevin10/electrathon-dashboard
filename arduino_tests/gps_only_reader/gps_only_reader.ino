#include <SoftwareSerial.h>
#include <TinyGPS++.h>

const byte gpsRxPin = 8;   // GPS TX -> Arduino pin 8
const byte gpsTxPin = 9;   // GPS RX -> Arduino pin 9 (optional for most modules)
const unsigned long gpsBaudRate = 9600;
const unsigned long usbBaudRate = 115200;
const unsigned long noDataWarningMs = 5000;
const unsigned long noFixReportMs = 2000;

SoftwareSerial gpsSerial(gpsRxPin, gpsTxPin);
TinyGPSPlus gps;

char nmeaLine[120];
byte nmeaIndex = 0;

unsigned long lastGpsByteMs = 0;
unsigned long lastNoFixReportMs = 0;
bool announcedWaitingForData = false;

void printFix() {
  Serial.print(F("GPS FIX | lat="));
  Serial.print(gps.location.lat(), 6);
  Serial.print(F(" lon="));
  Serial.print(gps.location.lng(), 6);
  Serial.print(F(" sats="));
  Serial.print(gps.satellites.isValid() ? gps.satellites.value() : 0);
  Serial.print(F(" alt_m="));
  Serial.print(gps.altitude.isValid() ? gps.altitude.meters() : 0.0);
  Serial.print(F(" speed_mph="));
  Serial.println(gps.speed.isValid() ? gps.speed.mph() : 0.0);
}

void printTime() {
  if (!gps.date.isValid() || !gps.time.isValid()) {
    return;
  }

  Serial.print(F("GPS UTC | "));
  Serial.print(gps.date.year());
  Serial.print(F("-"));
  if (gps.date.month() < 10) {
    Serial.print(F("0"));
  }
  Serial.print(gps.date.month());
  Serial.print(F("-"));
  if (gps.date.day() < 10) {
    Serial.print(F("0"));
  }
  Serial.print(gps.date.day());
  Serial.print(F(" "));
  if (gps.time.hour() < 10) {
    Serial.print(F("0"));
  }
  Serial.print(gps.time.hour());
  Serial.print(F(":"));
  if (gps.time.minute() < 10) {
    Serial.print(F("0"));
  }
  Serial.print(gps.time.minute());
  Serial.print(F(":"));
  if (gps.time.second() < 10) {
    Serial.print(F("0"));
  }
  Serial.println(gps.time.second());
}

void printNmeaChar(char value) {
  if (value == '\r') {
    return;
  }

  if (value == '\n') {
    if (nmeaIndex > 0) {
      nmeaLine[nmeaIndex] = '\0';
      Serial.print(F("NMEA | "));
      Serial.println(nmeaLine);
      nmeaIndex = 0;
    }
    return;
  }

  if (nmeaIndex < sizeof(nmeaLine) - 1) {
    nmeaLine[nmeaIndex++] = value;
  } else {
    nmeaIndex = 0;
  }
}

void setup() {
  Serial.begin(usbBaudRate);
  gpsSerial.begin(gpsBaudRate);

  Serial.println();
  Serial.println(F("GPS-only reader started"));
  Serial.println(F("Expected wiring: GPS TX -> D8, GPS RX -> D9, power + ground"));
  Serial.println(F("Open Serial Monitor at 115200 baud"));
  Serial.println(F("Waiting for GPS data..."));
}

void loop() {
  while (gpsSerial.available() > 0) {
    const char incoming = static_cast<char>(gpsSerial.read());
    lastGpsByteMs = millis();
    announcedWaitingForData = true;

    printNmeaChar(incoming);
    gps.encode(incoming);
  }

  if (gps.location.isUpdated()) {
    printFix();
  }

  if (gps.date.isUpdated() || gps.time.isUpdated()) {
    printTime();
  }

  const unsigned long now = millis();

  if (lastGpsByteMs == 0 && !announcedWaitingForData && now >= noDataWarningMs) {
    Serial.println(F("No GPS bytes received yet. Check TX/RX wiring, power, and module baud."));
    announcedWaitingForData = true;
  }

  if (lastGpsByteMs > 0 && (now - lastGpsByteMs) >= noDataWarningMs) {
    Serial.println(F("GPS data stopped. Check wiring or module power."));
    lastGpsByteMs = now;
  }

  if (!gps.location.isValid() && (now - lastNoFixReportMs) >= noFixReportMs) {
    Serial.println(F("No GPS fix yet. Move the antenna outside and wait for satellites."));
    lastNoFixReportMs = now;
  }
}
