#include <Arduino.h>
#include <TinyGPS++.h>

// Standalone ESP32 GPS test.
//
// Wiring used by this project:
// - GPS TX -> ESP32 GPIO17 (UART2 RX)
// - GPS RX -> ESP32 GPIO16 (UART2 TX, often optional)
// - GPS GND -> ESP32 GND
// - GPS VCC -> module-rated supply
//
// Open Serial Monitor at 115200 baud.
// The GPS module is expected to output NMEA at 9600 baud.

const uint8_t gpsRxPin = 17;
const uint8_t gpsTxPin = 16;
const uint32_t usbSerialBaud = 115200;
const uint32_t gpsSerialBaud = 9600;

const unsigned long reportIntervalMs = 1000;
const unsigned long noFixReportIntervalMs = 2000;
const unsigned long noDataWarningDelayMs = 5000;

HardwareSerial gpsSerial(2);
TinyGPSPlus gps;

bool rawNmeaOutput = false;
bool warnedNoData = false;
unsigned long gpsBytesReceived = 0;
unsigned long sentencesWithFixBaseline = 0;
unsigned long failedChecksumBaseline = 0;
unsigned long lastReportTime = 0;
unsigned long lastNoFixReportTime = 0;

void printTwoDigits(int value) {
  if (value < 10) {
    Serial.print('0');
  }
  Serial.print(value);
}

void printHelp() {
  Serial.println(F("Commands:"));
  Serial.println(F("  ? or h : print this help"));
  Serial.println(F("  r      : toggle raw NMEA passthrough"));
  Serial.println(F("  s      : print GPS status now"));
  Serial.println(F("  z      : reset byte/sentence/checksum counters"));
}

unsigned long currentSentencesWithFix() {
  return gps.sentencesWithFix() - sentencesWithFixBaseline;
}

unsigned long currentFailedChecksumCount() {
  return gps.failedChecksum() - failedChecksumBaseline;
}

void printGpsTime() {
  if (!gps.date.isValid() || !gps.time.isValid()) {
    Serial.println(F("GPSTIME:NOFIX"));
    return;
  }

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
}

void printFixReport() {
  Serial.print(F("GPS:"));
  Serial.print(gps.location.lat(), 6);
  Serial.print(',');
  Serial.print(gps.location.lng(), 6);
  Serial.print(',');
  Serial.println(gps.satellites.isValid() ? gps.satellites.value() : 0);

  printGpsTime();

  Serial.print(F("STATUS:FIX sats="));
  Serial.print(gps.satellites.isValid() ? gps.satellites.value() : 0);
  Serial.print(F(" hdop="));
  if (gps.hdop.isValid()) {
    Serial.print(gps.hdop.hdop(), 1);
  } else {
    Serial.print(F("NA"));
  }
  Serial.print(F(" speed_kmph="));
  if (gps.speed.isValid()) {
    Serial.print(gps.speed.kmph(), 2);
  } else {
    Serial.print(F("NA"));
  }
  Serial.print(F(" altitude_m="));
  if (gps.altitude.isValid()) {
    Serial.print(gps.altitude.meters(), 1);
  } else {
    Serial.print(F("NA"));
  }
  Serial.print(F(" age_ms="));
  Serial.print(gps.location.age());
  Serial.print(F(" chars="));
  Serial.print(gpsBytesReceived);
  Serial.print(F(" sentences="));
  Serial.print(currentSentencesWithFix());
  Serial.print(F(" checksum_fail="));
  Serial.println(currentFailedChecksumCount());
}

void printNoFixReport() {
  Serial.println(F("GPS:NOFIX"));
  Serial.println(F("GPSTIME:NOFIX"));
  Serial.print(F("STATUS:WAITING_FOR_FIX sats="));
  Serial.print(gps.satellites.isValid() ? gps.satellites.value() : 0);
  Serial.print(F(" chars="));
  Serial.print(gpsBytesReceived);
  Serial.print(F(" encoded_chars="));
  Serial.print(gps.charsProcessed());
  Serial.print(F(" sentences="));
  Serial.print(currentSentencesWithFix());
  Serial.print(F(" checksum_fail="));
  Serial.println(currentFailedChecksumCount());
}

void printStatusNow() {
  if (gps.location.isValid()) {
    printFixReport();
  } else {
    printNoFixReport();
  }
}

void resetCounters() {
  gpsBytesReceived = 0;
  sentencesWithFixBaseline = gps.sentencesWithFix();
  failedChecksumBaseline = gps.failedChecksum();
  warnedNoData = false;
  Serial.println(F("STATUS:COUNTERS_RESET"));
}

void serviceUsbCommands() {
  while (Serial.available() > 0) {
    const char command = static_cast<char>(Serial.read());

    switch (command) {
      case '?':
      case 'h':
      case 'H':
        printHelp();
        break;

      case 'r':
      case 'R':
        rawNmeaOutput = !rawNmeaOutput;
        Serial.print(F("RAW_NMEA:"));
        Serial.println(rawNmeaOutput ? F("ON") : F("OFF"));
        break;

      case 's':
      case 'S':
        printStatusNow();
        break;

      case 'z':
      case 'Z':
        resetCounters();
        break;

      case '\r':
      case '\n':
        break;

      default:
        Serial.print(F("STATUS:UNKNOWN_COMMAND "));
        Serial.println(command);
        printHelp();
        break;
    }
  }
}

void serviceGpsInput() {
  while (gpsSerial.available() > 0) {
    const char value = static_cast<char>(gpsSerial.read());
    gpsBytesReceived++;

    if (rawNmeaOutput) {
      Serial.write(value);
    }

    gps.encode(value);
  }
}

void setup() {
  Serial.begin(usbSerialBaud);
  gpsSerial.begin(gpsSerialBaud, SERIAL_8N1, gpsRxPin, gpsTxPin);

  delay(500);

  Serial.println();
  Serial.println(F("ESP32 GPS test ready"));
  Serial.println(F("Wiring: GPS TX -> GPIO17, GPS RX -> GPIO16 optional"));
  Serial.println(F("GPS UART: UART2, 9600 baud, 8N1"));
  Serial.println(F("Serial monitor: 115200 baud"));
  printHelp();
}

void loop() {
  serviceUsbCommands();
  serviceGpsInput();

  const unsigned long now = millis();

  if (gps.location.isValid()) {
    if (now - lastReportTime >= reportIntervalMs) {
      lastReportTime = now;
      printFixReport();
    }
  } else if (now - lastNoFixReportTime >= noFixReportIntervalMs) {
    lastNoFixReportTime = now;
    printNoFixReport();
  }

  if (!warnedNoData && now >= noDataWarningDelayMs && gpsBytesReceived < 10) {
    warnedNoData = true;
    Serial.println(F("STATUS:NO_GPS_DATA Check power, common GND, GPS TX->GPIO17, and sky view."));
  }
}
