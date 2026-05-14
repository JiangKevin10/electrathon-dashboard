#include <Arduino.h>
#include <FS.h>
#include <SPI.h>
#include <SD.h>
#include <SD_MMC.h>

// Dedicated ESP32 SD card test.
//
// Open Serial Monitor at 115200 baud.
//
// This isolates the storage hardware from GPS / hall / button code and prints:
// - whether the card mounted
// - which SPI frequency worked
// - card type and size
// - whether write/read/delete passed
//
// If your SD module has an AMS1117-3.3 regulator, its VCC often needs the ESP32
// board's VIN/5V pin while the SPI signal lines still stay on 3.3V GPIO.
//
// Serial commands:
// - ? : print help
// - m : retry mount only
// - t : rerun the full SD test
// - l : list the root directory
// - p : print current status

const uint8_t statusLedPin = 26;

#define STORAGE_BACKEND_SD_SPI 1
#define STORAGE_BACKEND_SD_MMC 2

// Keep SPI mode for your external SD module.
#ifndef STORAGE_BACKEND
#define STORAGE_BACKEND STORAGE_BACKEND_SD_SPI
#endif

#if STORAGE_BACKEND == STORAGE_BACKEND_SD_SPI
const uint8_t sdSckPin = 18;
const uint8_t sdMisoPin = 19;
const uint8_t sdMosiPin = 23;
const uint8_t sdChipSelectPin = 5;
const uint32_t sdSpiFrequenciesHz[] = {
  400000UL,
  1000000UL,
  4000000UL,
  10000000UL
};
#endif

const unsigned long statusPrintIntervalMs = 4000;
const char* const sdTestPath = "/SDTEST.TXT";

bool sdMounted = false;
bool sdTestPassed = false;
uint32_t mountedFrequencyHz = 0;
unsigned long lastStatusPrintTime = 0;

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

bool storageBegin(uint32_t frequencyHz) {
#if STORAGE_BACKEND == STORAGE_BACKEND_SD_MMC
  (void)frequencyHz;
  return SD_MMC.begin("/sdcard");
#else
  SPI.begin(sdSckPin, sdMisoPin, sdMosiPin, sdChipSelectPin);
  return SD.begin(sdChipSelectPin, SPI, frequencyHz);
#endif
}

uint8_t storageCardType() {
#if STORAGE_BACKEND == STORAGE_BACKEND_SD_MMC
  return SD_MMC.cardType();
#else
  return SD.cardType();
#endif
}

uint64_t storageCardSizeBytes() {
#if STORAGE_BACKEND == STORAGE_BACKEND_SD_MMC
  return SD_MMC.cardSize();
#else
  return SD.cardSize();
#endif
}

const __FlashStringHelper* cardTypeText(uint8_t cardType) {
  switch (cardType) {
    case CARD_MMC:
      return F("MMC");
    case CARD_SD:
      return F("SDSC");
    case CARD_SDHC:
      return F("SDHC/SDXC");
    case CARD_NONE:
    default:
      return F("NONE");
  }
}

void signalResult(bool success) {
  const uint8_t flashes = success ? 2 : 1;
  const unsigned long onTimeMs = success ? 120 : 500;
  const unsigned long offTimeMs = 140;

  for (uint8_t i = 0; i < flashes; i++) {
    digitalWrite(statusLedPin, HIGH);
    delay(onTimeMs);
    digitalWrite(statusLedPin, LOW);
    delay(offTimeMs);
  }
}

void printHelp() {
  Serial.println(F("Commands: ?=help, m=retry mount, t=full test, l=list root, p=print status"));
}

void printWiringReminder() {
  Serial.println(F("SD wiring for SPI mode: SCK=GPIO18 MISO=GPIO19 MOSI=GPIO23 CS=GPIO5"));
  Serial.println(F("Keep SD GND tied to ESP32 GND."));
  Serial.println(F("If the module has AMS1117-3.3, its VCC often needs VIN/5V instead of 3V3."));
}

bool mountCard() {
  sdMounted = false;
  sdTestPassed = false;
  mountedFrequencyHz = 0;

  Serial.print(F("SD:MOUNT backend="));
  Serial.println(storageBackendName());

#if STORAGE_BACKEND == STORAGE_BACKEND_SD_MMC
  Serial.println(F("SD:TRY mode=SD_MMC"));
  if (storageBegin(0)) {
    sdMounted = true;
  }
#else
  for (size_t index = 0; index < (sizeof(sdSpiFrequenciesHz) / sizeof(sdSpiFrequenciesHz[0])); index++) {
    const uint32_t frequencyHz = sdSpiFrequenciesHz[index];
    Serial.print(F("SD:TRY freq_hz="));
    Serial.println(frequencyHz);

    if (storageBegin(frequencyHz)) {
      sdMounted = true;
      mountedFrequencyHz = frequencyHz;
      break;
    }

    delay(80);
  }
#endif

  if (!sdMounted) {
    Serial.println(F("SD:FAIL mount"));
    signalResult(false);
    return false;
  }

  const uint8_t cardType = storageCardType();
  Serial.print(F("SD:MOUNTED type="));
  Serial.print(cardTypeText(cardType));
  Serial.print(F(" size_mb="));
  Serial.print(static_cast<unsigned long>(storageCardSizeBytes() / (1024ULL * 1024ULL)));
#if STORAGE_BACKEND == STORAGE_BACKEND_SD_SPI
  Serial.print(F(" freq_hz="));
  Serial.print(mountedFrequencyHz);
#endif
  Serial.println();
  return true;
}

bool runWriteReadDeleteTest() {
  if (!sdMounted && !mountCard()) {
    return false;
  }

  if (storageFs().exists(sdTestPath) && !storageFs().remove(sdTestPath)) {
    Serial.println(F("SD:FAIL preclean"));
    signalResult(false);
    return false;
  }

  File writeFile = storageFs().open(sdTestPath, FILE_WRITE);
  if (!writeFile) {
    Serial.println(F("SD:FAIL open_write"));
    signalResult(false);
    return false;
  }

  char payload[64];
#if STORAGE_BACKEND == STORAGE_BACKEND_SD_SPI
  snprintf(payload, sizeof(payload), "sd-test freq=%lu", static_cast<unsigned long>(mountedFrequencyHz));
#else
  snprintf(payload, sizeof(payload), "sd-test backend=SD_MMC");
#endif

  const size_t expectedLength = strlen(payload);
  const size_t written = writeFile.write(reinterpret_cast<const uint8_t*>(payload), expectedLength);
  writeFile.close();

  if (written != expectedLength) {
    Serial.print(F("SD:FAIL short_write wrote="));
    Serial.println(static_cast<unsigned long>(written));
    signalResult(false);
    return false;
  }

  File readFile = storageFs().open(sdTestPath, FILE_READ);
  if (!readFile) {
    Serial.println(F("SD:FAIL open_read"));
    signalResult(false);
    return false;
  }

  char buffer[80] = {0};
  const size_t bytesRead = readFile.readBytes(buffer, sizeof(buffer) - 1);
  readFile.close();

  if (bytesRead != expectedLength || strcmp(buffer, payload) != 0) {
    Serial.println(F("SD:FAIL verify"));
    Serial.print(F("SD:EXPECTED "));
    Serial.println(payload);
    Serial.print(F("SD:ACTUAL   "));
    Serial.println(buffer);
    signalResult(false);
    return false;
  }

  if (!storageFs().remove(sdTestPath)) {
    Serial.println(F("SD:FAIL delete"));
    signalResult(false);
    return false;
  }

  sdTestPassed = true;
  Serial.println(F("SD:PASS write_read_delete"));
  signalResult(true);
  return true;
}

void listRootDirectory() {
  if (!sdMounted && !mountCard()) {
    return;
  }

  File root = storageFs().open("/");
  if (!root) {
    Serial.println(F("SD:FAIL open_root"));
    return;
  }

  Serial.println(F("ROOT:BEGIN"));
  while (true) {
    File entry = root.openNextFile();
    if (!entry) {
      break;
    }

    Serial.print(F("ROOT:ITEM name="));
    Serial.print(entry.name());
    Serial.print(F(" size="));
    Serial.println(entry.size());
    entry.close();
  }
  root.close();
  Serial.println(F("ROOT:END"));
}

void printStatus() {
  Serial.print(F("STATUS backend="));
  Serial.print(storageBackendName());
  Serial.print(F(" mounted="));
  Serial.print(sdMounted ? F("YES") : F("NO"));
  Serial.print(F(" test="));
  Serial.print(sdTestPassed ? F("PASS") : F("NOT_OK"));
#if STORAGE_BACKEND == STORAGE_BACKEND_SD_SPI
  Serial.print(F(" freq_hz="));
  Serial.print(mountedFrequencyHz);
#endif
  Serial.println();
}

void runFullTest() {
  Serial.println(F("SD:FULL_TEST"));
  const bool mounted = mountCard();
  if (mounted) {
    runWriteReadDeleteTest();
  }
  printStatus();
}

void handleSerialCommands() {
  while (Serial.available() > 0) {
    const char value = static_cast<char>(Serial.read());

    switch (value) {
      case '?':
      case 'h':
      case 'H':
        printHelp();
        break;

      case 'm':
      case 'M':
        mountCard();
        printStatus();
        break;

      case 't':
      case 'T':
        runFullTest();
        break;

      case 'l':
      case 'L':
        listRootDirectory();
        break;

      case 'p':
      case 'P':
        printStatus();
        break;

      case '\r':
      case '\n':
        break;

      default:
        Serial.print(F("INFO:Unknown command '"));
        Serial.print(value);
        Serial.println(F("'"));
        printHelp();
        break;
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(statusLedPin, OUTPUT);
  digitalWrite(statusLedPin, LOW);

#if STORAGE_BACKEND == STORAGE_BACKEND_SD_SPI
  pinMode(sdChipSelectPin, OUTPUT);
  digitalWrite(sdChipSelectPin, HIGH);
#endif

  Serial.println();
  Serial.println(F("ESP32 SD test ready"));
  Serial.print(F("BACKEND:"));
  Serial.println(storageBackendName());
  printWiringReminder();
  printHelp();
  runFullTest();
}

void loop() {
  handleSerialCommands();

  const unsigned long now = millis();
  if (now - lastStatusPrintTime >= statusPrintIntervalMs) {
    lastStatusPrintTime = now;
    printStatus();
  }
}
