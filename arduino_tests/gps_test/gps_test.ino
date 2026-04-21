#include <SoftwareSerial.h>
#include <TinyGPS++.h>

const byte arduinoRxFromGpsTxPin = 8;
const byte arduinoTxToGpsRxPin = 9;

const unsigned long reportInterval = 1000;
const unsigned long noFixReportInterval = 2000;
const unsigned long noDataWarningDelay = 5000;

SoftwareSerial gpsSerial(arduinoRxFromGpsTxPin, arduinoTxToGpsRxPin);
TinyGPSPlus gps;

unsigned long lastReportTime = 0;
unsigned long lastNoFixReportTime = 0;
void printTwoDigits(int value) {
  if (value < 10) {
    Serial.print('0');
  }
  Serial.print(value);
}

void printFixReport() {
  Serial.print(F("GPS:"));
  Serial.print(gps.location.lat(), 6);
  Serial.print(',');
  Serial.print(gps.location.lng(), 6);
  Serial.print(',');
  Serial.println(gps.satellites.isValid() ? gps.satellites.value() : 0);

  if (gps.date.isValid() && gps.time.isValid()) {
    Serial.print(F("GPSTIME:"));
    Serial.print(gps.date.year());
    Serial.print('-');
    printTwoDigits(gps.date.month());
    Serial.print('-');
    printTwoDigits(gps.date.day());
    Serial.print(',');
    printTwoDigits(gps.time.hour());
    Serial.print(':');
    printTwoDigits(gps.time.minute());
    Serial.print(':');
    printTwoDigits(gps.time.second());
    Serial.println();
  } else {
    Serial.println(F("GPSTIME:NOFIX"));
  }

  Serial.print(F("STATUS:FIX sats="));
  Serial.print(gps.satellites.isValid() ? gps.satellites.value() : 0);
  Serial.print(F(" chars="));
  Serial.print(gps.charsProcessed());
  Serial.print(F(" age_ms="));
  Serial.println(gps.location.age());
}

void printNoFixReport() {
  Serial.println(F("GPS:NOFIX"));
  Serial.println(F("GPSTIME:NOFIX"));
  Serial.print(F("STATUS:WAITING_FOR_FIX sats="));
  Serial.print(gps.satellites.isValid() ? gps.satellites.value() : 0);
  Serial.print(F(" chars="));
  Serial.println(gps.charsProcessed());
}

void setup() {
  Serial.begin(115200);
  gpsSerial.begin(9600);

  Serial.println(F("GPS test ready"));
  Serial.println(F("Wiring: GPS TX -> D8, GPS RX -> D9"));
  Serial.println(F("GPS serial baud: 9600"));
  Serial.println(F("Serial monitor: 115200 baud"));
}

void loop() {
  while (gpsSerial.available() > 0) {
    gps.encode(gpsSerial.read());
  }

  const unsigned long now = millis();

  if (gps.location.isValid()) {
    if (now - lastReportTime >= reportInterval) {
      lastReportTime = now;
      printFixReport();
    }
  } else if (now - lastNoFixReportTime >= noFixReportInterval) {
    lastNoFixReportTime = now;
    printNoFixReport();
  }

  if (now >= noDataWarningDelay && gps.charsProcessed() < 10) {
    static bool warnedNoData = false;
    if (!warnedNoData) {
      warnedNoData = true;
      Serial.println(F("STATUS:NO_GPS_DATA Check wiring, module power, and sky view."));
    }
  }
}
