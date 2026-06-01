#include <Arduino.h>
#include <SPI.h>
#include <SD.h>

// Simple SD card test.
// Wiring: SCK=18, MISO=19, MOSI=23, CS=5
// Open Serial Monitor at 115200 baud.

const uint8_t sdSckPin  = 18;
const uint8_t sdMisoPin = 19;
const uint8_t sdMosiPin = 23;
const uint8_t sdCsPin   = 5;

const char* testPath = "/SDTEST.TXT";
const char* testPayload = "sd card test ok";

const uint32_t speedsToTry[] = { 400000, 1000000, 4000000, 16000000 };
const char*    speedLabels[]  = { "400kHz", "1MHz", "4MHz", "16MHz" };
const uint8_t  speedCount     = 4;

bool tryMount(uint32_t freq, const char* label) {
  SD.end();
  delay(100);
  SPI.begin(sdSckPin, sdMisoPin, sdMosiPin, sdCsPin);
  Serial.print("  Trying ");
  Serial.print(label);
  Serial.print("... ");
  if (SD.begin(sdCsPin, SPI, freq)) {
    Serial.println("MOUNTED");
    return true;
  }
  Serial.println("fail");
  return false;
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("=== SD Card Test ===");

  uint32_t workingFreq = 0;
  const char* workingLabel = nullptr;

  for (uint8_t i = 0; i < speedCount; i++) {
    if (tryMount(speedsToTry[i], speedLabels[i])) {
      workingFreq = speedsToTry[i];
      workingLabel = speedLabels[i];
      break;
    }
  }

  if (workingFreq == 0) {
    Serial.println();
    Serial.println("FAIL - card did not mount at any speed");
    Serial.println("Check: card inserted, FAT32 format, wiring on pins 18/19/23/5");
    return;
  }

  uint64_t sizeMB = SD.cardSize() / (1024ULL * 1024ULL);
  Serial.print("Card size: ");
  Serial.print((unsigned long)sizeMB);
  Serial.print(" MB  |  Working speed: ");
  Serial.println(workingLabel);

  // Write
  Serial.print("Writing...  ");
  if (SD.exists(testPath)) SD.remove(testPath);
  File f = SD.open(testPath, FILE_WRITE);
  if (!f) { Serial.println("FAIL - could not open file for writing"); return; }
  f.print(testPayload);
  f.close();
  Serial.println("OK");

  // Read back
  Serial.print("Reading...  ");
  f = SD.open(testPath, FILE_READ);
  if (!f) { Serial.println("FAIL - could not open file for reading"); return; }
  String result = f.readString();
  f.close();
  if (result == testPayload) {
    Serial.println("OK");
  } else {
    Serial.print("FAIL - got: ");
    Serial.println(result);
    return;
  }

  SD.remove(testPath);
  Serial.println();
  Serial.println(">>> SD CARD PASS <<<");
  Serial.print(">>> Use this speed in your firmware: ");
  Serial.print(workingLabel);
  Serial.println(" <<<");
}

void loop() {}
