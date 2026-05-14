#include <Arduino.h>
#include <FS.h>
#include <SPI.h>
#include <SD.h>
#include <SD_MMC.h>
#include <TinyGPS++.h>
#include <string.h>

// Standalone ESP32 bring-up sketch for the currently wired hardware.
// This intentionally does not touch the optional IMU.
//
// Open the serial monitor at 115200 baud and verify:
// - the LED on GPIO26 blinks
// - the button on GPIO27 reports PRESSED/RELEASED
// - the hall sensor on GPIO25 increments the count
// - the GPS on UART2 (GPIO16/GPIO17) starts reporting data
// - the SD card mounts and passes a write/read/delete test
//
// Serial commands:
// - ? : print help
// - p : print a full status line now
// - s : rerun the SD card test
// - z : reset the hall counter
// - l : flash the LED three times

const uint8_t hallPin = 25;
const uint8_t buttonPin = 27;
const uint8_t statusLedPin = 26;
const uint8_t gpsRxPin = 16;
const uint8_t gpsTxPin = 17;

#define STORAGE_BACKEND_SD_SPI 1
#define STORAGE_BACKEND_SD_MMC 2

// Change to STORAGE_BACKEND_SD_MMC if your ESP32 board uses an onboard SD slot.
#ifndef STORAGE_BACKEND
#define STORAGE_BACKEND STORAGE_BACKEND_SD_SPI
#endif

#if STORAGE_BACKEND == STORAGE_BACKEND_SD_SPI
const uint8_t sdSckPin = 18;
const uint8_t sdMisoPin = 19;
const uint8_t sdMosiPin = 23;
const uint8_t sdChipSelectPin = 5;
#endif

const unsigned long buttonDebounceMs = 50;
const unsigned long statusReportIntervalMs = 1000;
const unsigned long gpsNoDataWarningDelayMs = 5000;
const unsigned long ledBlinkIntervalMs = 500;
const char* const sdTestPath = "/HWTEST.TXT";

HardwareSerial gpsSerial(2);
TinyGPSPlus gps;

volatile unsigned long hallCount = 0;
portMUX_TYPE hallCountMux = portMUX_INITIALIZER_UNLOCKED;

bool lastRawButtonReading = HIGH;
bool stableButtonState = HIGH;
bool ledState = LOW;
bool sdMounted = false;
bool sdTestPassed = false;
bool gpsWarnedNoData = false;

unsigned long lastButtonDebounceTime = 0;
unsigned long lastStatusReportTime = 0;
unsigned long lastLedToggleTime = 0;
unsigned long lastPrintedHallCount = 0;

void IRAM_ATTR hallISR() {
  portENTER_CRITICAL_ISR(&hallCountMux);
  hallCount++;
  portEXIT_CRITICAL_ISR(&hallCountMux);
}

unsigned long readHallCount() {
  portENTER_CRITICAL(&hallCountMux);
  const unsigned long snapshot = hallCount;
  portEXIT_CRITICAL(&hallCountMux);
  return snapshot;
}

void resetHallCount() {
  portENTER_CRITICAL(&hallCountMux);
  hallCount = 0;
  portEXIT_CRITICAL(&hallCountMux);
}

const __FlashStringHelper* buttonStateText(bool reading) {
  return reading == LOW ? F("PRESSED") : F("RELEASED");
}

const __FlashStringHelper* storageBackendName() {
#if STORAGE_BACKEND == STORAGE_BACKEND_SD_MMC
  return F("SD_MMC");
#else
  return F("SD_SPI");
#endif
}

fs::FS& storageFs() {
#if STORAGE_BACKEND == STORAGE_BACKEND_SD_MMC
  return SD_MMC;
#else
  return SD;
#endif
}

bool storageBegin() {
#if STORAGE_BACKEND == STORAGE_BACKEND_SD_MMC
  return SD_MMC.begin("/sdcard");
#else
  SPI.begin(sdSckPin, sdMisoPin, sdMosiPin, sdChipSelectPin);
  return SD.begin(sdChipSelectPin, SPI);
#endif
}

uint64_t storageCardSizeBytes() {
#if STORAGE_BACKEND == STORAGE_BACKEND_SD_MMC
  return SD_MMC.cardSize();
#else
  return SD.cardSize();
#endif
}

void printHelp() {
  Serial.println(F("Commands: ?=help, p=print status, s=rerun SD test, z=reset hall count, l=flash LED"));
}

void flashLed(uint8_t flashes, unsigned long onMs, unsigned long offMs) {
  for (uint8_t i = 0; i < flashes; i++) {
    digitalWrite(statusLedPin, HIGH);
    delay(onMs);
    digitalWrite(statusLedPin, LOW);
    delay(offMs);
  }
  ledState = LOW;
  lastLedToggleTime = millis();
}

void runSdCardTest() {
  Serial.print(F("SD:START backend="));
  Serial.println(storageBackendName());

  sdMounted = storageBegin();
  sdTestPassed = false;

  if (!sdMounted) {
    Serial.println(F("SD:FAIL mount"));
    return;
  }

  const uint64_t cardSizeBytes = storageCardSizeBytes();
  Serial.print(F("SD:MOUNTED size_mb="));
  Serial.println(static_cast<unsigned long>(cardSizeBytes / (1024ULL * 1024ULL)));

  if (storageFs().exists(sdTestPath) && !storageFs().remove(sdTestPath)) {
    Serial.println(F("SD:FAIL preclean"));
    return;
  }

  File testFile = storageFs().open(sdTestPath, FILE_WRITE);
  if (!testFile) {
    Serial.println(F("SD:FAIL open_write"));
    return;
  }

  const char payload[] = "esp32 bringup test";
  const size_t expectedLength = sizeof(payload) - 1;
  const size_t written = testFile.write(
    reinterpret_cast<const uint8_t*>(payload),
    expectedLength
  );
  testFile.close();

  if (written != expectedLength) {
    Serial.println(F("SD:FAIL short_write"));
    return;
  }

  File readFile = storageFs().open(sdTestPath, FILE_READ);
  if (!readFile) {
    Serial.println(F("SD:FAIL open_read"));
    return;
  }

  char buffer[32] = {0};
  const size_t bytesRead = readFile.readBytes(buffer, sizeof(buffer) - 1);
  readFile.close();

  if (bytesRead != expectedLength || strncmp(buffer, payload, expectedLength) != 0) {
    Serial.println(F("SD:FAIL verify"));
    return;
  }

  if (!storageFs().remove(sdTestPath)) {
    Serial.println(F("SD:WARN delete_failed"));
  }

  sdTestPassed = true;
  Serial.println(F("SD:PASS write_read_delete"));
}

void printGpsStatus() {
  if (gps.location.isValid()) {
    Serial.print(F(" gps=FIX sats="));
    Serial.print(gps.satellites.isValid() ? gps.satellites.value() : 0);
    Serial.print(F(" lat="));
    Serial.print(gps.location.lat(), 6);
    Serial.print(F(" lon="));
    Serial.print(gps.location.lng(), 6);
    Serial.print(F(" age_ms="));
    Serial.print(gps.location.age());
    return;
  }

  Serial.print(F(" gps=NOFIX sats="));
  Serial.print(gps.satellites.isValid() ? gps.satellites.value() : 0);
  Serial.print(F(" chars="));
  Serial.print(gps.charsProcessed());
}

void printStatusLine() {
  Serial.print(F("STATUS hall="));
  Serial.print(readHallCount());
  Serial.print(F(" button="));
  Serial.print(buttonStateText(stableButtonState));
  Serial.print(F(" sd="));
  if (sdTestPassed) {
    Serial.print(F("PASS"));
  } else if (sdMounted) {
    Serial.print(F("MOUNT_ONLY"));
  } else {
    Serial.print(F("FAIL"));
  }

  printGpsStatus();
  Serial.println();
}

void serviceHallReporting() {
  const unsigned long currentCount = readHallCount();
  if (currentCount == lastPrintedHallCount) {
    return;
  }

  lastPrintedHallCount = currentCount;
  Serial.print(F("HALL:count="));
  Serial.println(currentCount);
}

void serviceButton() {
  const bool reading = digitalRead(buttonPin);
  const unsigned long now = millis();

  if (reading != lastRawButtonReading) {
    lastButtonDebounceTime = now;
    lastRawButtonReading = reading;
  }

  if ((now - lastButtonDebounceTime) < buttonDebounceMs) {
    return;
  }

  if (reading == stableButtonState) {
    return;
  }

  stableButtonState = reading;
  Serial.print(F("BUTTON:"));
  Serial.println(buttonStateText(stableButtonState));
}

void serviceGps() {
  while (gpsSerial.available() > 0) {
    gps.encode(gpsSerial.read());
  }

  if (!gpsWarnedNoData && millis() >= gpsNoDataWarningDelayMs && gps.charsProcessed() < 10) {
    gpsWarnedNoData = true;
    Serial.println(F("GPS:WARN no serial data yet; check power, TX->GPIO16, and sky view."));
  }
}

void serviceLedHeartbeat() {
  const unsigned long now = millis();
  if (now - lastLedToggleTime < ledBlinkIntervalMs) {
    return;
  }

  lastLedToggleTime = now;
  ledState = !ledState;
  digitalWrite(statusLedPin, ledState ? HIGH : LOW);
}

void serviceSerialCommands() {
  while (Serial.available() > 0) {
    const char command = static_cast<char>(Serial.read());

    switch (command) {
      case '?':
      case 'h':
      case 'H':
        printHelp();
        break;

      case 'p':
      case 'P':
        printStatusLine();
        break;

      case 's':
      case 'S':
        runSdCardTest();
        break;

      case 'z':
      case 'Z':
        resetHallCount();
        lastPrintedHallCount = 0;
        Serial.println(F("HALL:reset"));
        break;

      case 'l':
      case 'L':
        Serial.println(F("LED:flash"));
        flashLed(3, 120, 120);
        break;

      case '\r':
      case '\n':
        break;

      default:
        Serial.print(F("INFO:Unknown command '"));
        Serial.print(command);
        Serial.println(F("'"));
        printHelp();
        break;
    }
  }
}

void setup() {
  Serial.begin(115200);
  gpsSerial.begin(9600, SERIAL_8N1, gpsRxPin, gpsTxPin);

  pinMode(hallPin, INPUT_PULLUP);
  pinMode(buttonPin, INPUT_PULLUP);
  pinMode(statusLedPin, OUTPUT);
  digitalWrite(statusLedPin, LOW);

#if STORAGE_BACKEND == STORAGE_BACKEND_SD_SPI
  pinMode(sdChipSelectPin, OUTPUT);
  digitalWrite(sdChipSelectPin, HIGH);
#endif

  attachInterrupt(digitalPinToInterrupt(hallPin), hallISR, FALLING);

  Serial.println();
  Serial.println(F("ESP32 bring-up test ready"));
  Serial.println(F("IMU:SKIPPED"));
  Serial.print(F("STORAGE_BACKEND:"));
  Serial.println(storageBackendName());
  Serial.println(F("Pins: hall=25 button=27 led=26 gps_rx=16 gps_tx=17"));
  Serial.println(F("Check the LED heartbeat, press the button, trigger the hall sensor, and wait for GPS."));
  printHelp();

  flashLed(2, 150, 150);
  runSdCardTest();
  printStatusLine();
}

void loop() {
  serviceSerialCommands();
  serviceGps();
  serviceButton();
  serviceHallReporting();
  serviceLedHeartbeat();

  const unsigned long now = millis();
  if (now - lastStatusReportTime >= statusReportIntervalMs) {
    lastStatusReportTime = now;
    printStatusLine();
  }
}
