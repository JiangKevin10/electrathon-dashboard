#include <SPI.h>
#include <SD.h>
#include <SoftwareSerial.h>
#include <TinyGPS++.h>
#include <string.h>

const byte hallPin = 2;
const byte buttonPin = 4;
const byte ledPin = 7;
const byte gpsRxPin = 8;
const byte gpsTxPin = 9;
const byte chipSelect = 10;

const unsigned long debounceDelay = 50;
const unsigned long dashboardSendInterval = 100;
const unsigned long gpsNoFixReportInterval = 2000;
const unsigned long rawLogWriteInterval = 500;
const byte syncedRaceRetentionCount = 5;

SoftwareSerial gpsSerial(gpsRxPin, gpsTxPin);
TinyGPSPlus gps;
File raceFile;

volatile unsigned long count = 0;

bool sdReady = false;
bool loggingState = false;
bool lastButtonReading = HIGH;
bool stableButtonState = HIGH;

unsigned long lastDebounceTime = 0;
unsigned long lastDashboardSendTime = 0;
unsigned long lastGpsNoFixReportTime = 0;
unsigned long lastRawLogTime = 0;
unsigned long raceStartMillis = 0;
unsigned long raceStartCount = 0;

char currentRaceFilename[12] = "";
char commandBuffer[32] = "";
byte commandLength = 0;

unsigned long readHallCount() {
  noInterrupts();
  const unsigned long snapshot = count;
  interrupts();
  return snapshot;
}

bool isDigitChar(char value) {
  return value >= '0' && value <= '9';
}

bool isRaceFilename(const char* filename, char prefix) {
  if (!filename || strlen(filename) != 11) {
    return false;
  }

  if (filename[0] != prefix || filename[7] != '.') {
    return false;
  }

  for (byte index = 1; index <= 6; index++) {
    if (!isDigitChar(filename[index])) {
      return false;
    }
  }

  return filename[8] == 'C' && filename[9] == 'S' && filename[10] == 'V';
}

bool isAnyRaceFilename(const char* filename) {
  return isRaceFilename(filename, 'R') || isRaceFilename(filename, 'S');
}

unsigned long extractRaceSequence(const char* filename) {
  if (!isAnyRaceFilename(filename)) {
    return 0;
  }

  unsigned long value = 0;
  for (byte index = 1; index <= 6; index++) {
    value = (value * 10UL) + static_cast<unsigned long>(filename[index] - '0');
  }
  return value;
}

unsigned long findNextRaceSequence() {
  unsigned long maxSequence = 0;
  File root = SD.open("/");
  if (!root) {
    return 1;
  }

  while (true) {
    File entry = root.openNextFile();
    if (!entry) {
      break;
    }

    const char* entryName = entry.name();
    const unsigned long sequence = extractRaceSequence(entryName);
    if (sequence > maxSequence) {
      maxSequence = sequence;
    }
    entry.close();
  }

  root.close();
  return maxSequence + 1;
}

bool copyFile(const char* sourceName, const char* targetName) {
  File sourceFile = SD.open(sourceName, FILE_READ);
  if (!sourceFile) {
    return false;
  }

  if (SD.exists(targetName)) {
    SD.remove(targetName);
  }

  File targetFile = SD.open(targetName, FILE_WRITE);
  if (!targetFile) {
    sourceFile.close();
    return false;
  }

  while (sourceFile.available()) {
    targetFile.write(sourceFile.read());
  }

  targetFile.flush();
  sourceFile.close();
  targetFile.close();
  return true;
}

void pruneSyncedRaces() {
  while (true) {
    byte syncedCount = 0;
    unsigned long oldestSequence = 0;
    char oldestFilename[16] = "";

    File root = SD.open("/");
    if (!root) {
      return;
    }

    while (true) {
      File entry = root.openNextFile();
      if (!entry) {
        break;
      }

      const char* entryName = entry.name();
      if (isRaceFilename(entryName, 'S')) {
        syncedCount++;
        const unsigned long sequence = extractRaceSequence(entryName);
        if (oldestSequence == 0 || sequence < oldestSequence) {
          oldestSequence = sequence;
          strncpy(oldestFilename, entryName, sizeof(oldestFilename) - 1);
          oldestFilename[sizeof(oldestFilename) - 1] = '\0';
        }
      }

      entry.close();
    }

    root.close();

    if (syncedCount <= syncedRaceRetentionCount || oldestFilename[0] == '\0') {
      return;
    }

    SD.remove(oldestFilename);
  }
}

void sendGpsState() {
  if (!gps.location.isValid()) {
    Serial.println(F("GPS:NOFIX"));
    return;
  }

  Serial.print(F("GPS:"));
  Serial.print(gps.location.lat(), 6);
  Serial.write(',');
  Serial.print(gps.location.lng(), 6);
  Serial.write(',');
  Serial.println(gps.satellites.isValid() ? gps.satellites.value() : 0);
}

void sendGpsTimeState() {
  if (!gps.date.isValid() || !gps.time.isValid()) {
    Serial.println(F("GPSTIME:NOFIX"));
    return;
  }

  Serial.print(F("GPSTIME:"));
  Serial.print(gps.date.year());
  Serial.write('-');
  if (gps.date.month() < 10) {
    Serial.write('0');
  }
  Serial.print(gps.date.month());
  Serial.write('-');
  if (gps.date.day() < 10) {
    Serial.write('0');
  }
  Serial.print(gps.date.day());
  Serial.write(',');
  if (gps.time.hour() < 10) {
    Serial.write('0');
  }
  Serial.print(gps.time.hour());
  Serial.write(':');
  if (gps.time.minute() < 10) {
    Serial.write('0');
  }
  Serial.print(gps.time.minute());
  Serial.write(':');
  if (gps.time.second() < 10) {
    Serial.write('0');
  }
  Serial.println(gps.time.second());
}

void formatGpsDate(char* buffer, size_t size) {
  if (!gps.date.isValid()) {
    buffer[0] = '\0';
    return;
  }

  snprintf(buffer, size, "%04d-%02d-%02d", gps.date.year(), gps.date.month(), gps.date.day());
}

void formatGpsTime(char* buffer, size_t size) {
  if (!gps.time.isValid()) {
    buffer[0] = '\0';
    return;
  }

  snprintf(buffer, size, "%02d:%02d:%02d", gps.time.hour(), gps.time.minute(), gps.time.second());
}

void writeRaceSample(bool forceWrite) {
  if (!loggingState || !raceFile) {
    return;
  }

  const unsigned long now = millis();
  if (!forceWrite && (now - lastRawLogTime) < rawLogWriteInterval) {
    return;
  }

  const unsigned long currentCount = readHallCount();
  const unsigned long elapsedMs = now - raceStartMillis;
  const unsigned long sessionCount = currentCount - raceStartCount;
  char gpsDateBuffer[16];
  char gpsTimeBuffer[16];
  formatGpsDate(gpsDateBuffer, sizeof(gpsDateBuffer));
  formatGpsTime(gpsTimeBuffer, sizeof(gpsTimeBuffer));

  raceFile.print(elapsedMs);
  raceFile.print(",");
  raceFile.print(sessionCount);
  raceFile.print(",");

  if (gps.location.isValid()) {
    raceFile.print(gps.location.lat(), 6);
  }
  raceFile.print(",");

  if (gps.location.isValid()) {
    raceFile.print(gps.location.lng(), 6);
  }
  raceFile.print(",");
  raceFile.print(gps.location.isValid() ? 1 : 0);
  raceFile.print(",");
  raceFile.print(gps.satellites.isValid() ? gps.satellites.value() : 0);
  raceFile.print(",");
  raceFile.print(gpsDateBuffer);
  raceFile.print(",");
  raceFile.println(gpsTimeBuffer);
  raceFile.flush();

  lastRawLogTime = now;
}

bool startRaceLogging() {
  if (!sdReady) {
    Serial.println(F("ERROR:SD_NOT_READY"));
    return false;
  }

  const unsigned long nextSequence = findNextRaceSequence();
  snprintf(currentRaceFilename, sizeof(currentRaceFilename), "R%06lu.CSV", nextSequence);

  raceFile = SD.open(currentRaceFilename, FILE_WRITE);
  if (!raceFile) {
    currentRaceFilename[0] = '\0';
    Serial.println(F("ERROR:RACE_OPEN_FAILED"));
    return false;
  }

  raceFile.println("elapsed_ms,count,latitude,longitude,gps_fix,gps_satellites,gps_utc_date,gps_utc_time");
  raceFile.flush();

  raceStartMillis = millis();
  raceStartCount = readHallCount();
  lastRawLogTime = 0;
  loggingState = true;
  digitalWrite(ledPin, HIGH);
  Serial.print(F("RACEFILE:"));
  Serial.println(currentRaceFilename);
  writeRaceSample(true);
  return true;
}

void stopRaceLogging() {
  if (!loggingState) {
    return;
  }

  writeRaceSample(true);

  if (raceFile) {
    raceFile.flush();
    raceFile.close();
  }

  loggingState = false;
  digitalWrite(ledPin, LOW);
  Serial.println(F("RACEFILE:"));
}

void handleButtonState() {
  const bool reading = digitalRead(buttonPin);

  if (reading != lastButtonReading) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (reading != stableButtonState) {
      stableButtonState = reading;

      if (stableButtonState == LOW) {
        if (loggingState) {
          stopRaceLogging();
        } else {
          startRaceLogging();
        }
      }
    }
  }

  lastButtonReading = reading;
}

void sendDashboardState(unsigned long now) {
  if (now - lastDashboardSendTime < dashboardSendInterval) {
    return;
  }

  Serial.print(F("COUNT:"));
  Serial.println(readHallCount());

  Serial.print(F("LOG:"));
  Serial.println(loggingState ? 1 : 0);

  Serial.print(F("RACEFILE:"));
  if (loggingState) {
    Serial.println(currentRaceFilename);
  } else {
    Serial.println();
  }

  lastDashboardSendTime = now;
}

void sendGpsUpdates(unsigned long now) {
  if (gps.location.isUpdated()) {
    sendGpsState();
  } else if (!gps.location.isValid() && now - lastGpsNoFixReportTime >= gpsNoFixReportInterval) {
    Serial.println(F("GPS:NOFIX"));
    lastGpsNoFixReportTime = now;
  }

  if (gps.date.isUpdated() || gps.time.isUpdated()) {
    sendGpsTimeState();
  } else if ((!gps.date.isValid() || !gps.time.isValid()) && now - lastGpsNoFixReportTime >= gpsNoFixReportInterval) {
    Serial.println(F("GPSTIME:NOFIX"));
    lastGpsNoFixReportTime = now;
  }
}

void sendRaceList() {
  if (!sdReady) {
    Serial.println(F("ERROR:SD_NOT_READY"));
    return;
  }

  if (loggingState) {
    Serial.println(F("ERROR:BUSY"));
    return;
  }

  Serial.println(F("LIST:BEGIN"));

  File root = SD.open("/");
  if (root) {
    while (true) {
      File entry = root.openNextFile();
      if (!entry) {
        break;
      }

      const char* entryName = entry.name();
      if (isRaceFilename(entryName, 'R')) {
        Serial.print(F("LIST:ITEM:"));
        Serial.print(entryName);
        Serial.write(',');
        Serial.println(entry.size());
      }

      entry.close();
    }
    root.close();
  }

  Serial.println(F("LIST:END"));
}

void sendRaceFile(const char* raceId) {
  if (!sdReady) {
    Serial.println(F("ERROR:SD_NOT_READY"));
    return;
  }

  if (loggingState) {
    Serial.println(F("ERROR:BUSY"));
    return;
  }

  if (!isRaceFilename(raceId, 'R')) {
    Serial.println(F("ERROR:INVALID_RACE_ID"));
    return;
  }

  File file = SD.open(raceId, FILE_READ);
  if (!file) {
    Serial.println(F("ERROR:RACE_NOT_FOUND"));
    return;
  }

  Serial.print(F("FILE:BEGIN:"));
  Serial.print(raceId);
  Serial.write(',');
  Serial.println(file.size());

  char lineBuffer[96];
  byte lineLength = 0;
  while (file.available()) {
    const char value = static_cast<char>(file.read());
    if (value == '\r') {
      continue;
    }

    if (value == '\n') {
      lineBuffer[lineLength] = '\0';
      Serial.print(F("FILE:DATA:"));
      Serial.println(lineBuffer);
      lineLength = 0;
      continue;
    }

    if (lineLength < sizeof(lineBuffer) - 1) {
      lineBuffer[lineLength++] = value;
    }
  }

  if (lineLength > 0) {
    lineBuffer[lineLength] = '\0';
    Serial.print(F("FILE:DATA:"));
    Serial.println(lineBuffer);
  }

  file.close();

  Serial.print(F("FILE:END:"));
  Serial.println(raceId);
}

void acknowledgeRace(const char* raceId) {
  if (!sdReady) {
    Serial.println(F("ERROR:SD_NOT_READY"));
    return;
  }

  if (!isRaceFilename(raceId, 'R')) {
    Serial.println(F("ERROR:INVALID_RACE_ID"));
    return;
  }

  char syncedFilename[16];
  strncpy(syncedFilename, raceId, sizeof(syncedFilename) - 1);
  syncedFilename[sizeof(syncedFilename) - 1] = '\0';
  syncedFilename[0] = 'S';

  if (!copyFile(raceId, syncedFilename)) {
    Serial.println(F("ERROR:SYNC_MARK_FAILED"));
    return;
  }

  if (!SD.remove(raceId)) {
    Serial.println(F("ERROR:SYNC_REMOVE_FAILED"));
    return;
  }

  pruneSyncedRaces();
  Serial.print(F("ACK:OK:"));
  Serial.println(raceId);
}

void deleteStoredRace(const char* raceId) {
  if (!sdReady) {
    Serial.println(F("ERROR:SD_NOT_READY"));
    return;
  }

  if (loggingState) {
    Serial.println(F("ERROR:BUSY"));
    return;
  }

  if (!isAnyRaceFilename(raceId)) {
    Serial.println(F("ERROR:INVALID_RACE_ID"));
    return;
  }

  if (!SD.exists(raceId)) {
    Serial.println(F("ERROR:RACE_NOT_FOUND"));
    return;
  }

  if (!SD.remove(raceId)) {
    Serial.println(F("ERROR:DELETE_FAILED"));
    return;
  }

  Serial.print(F("DELETE:OK:"));
  Serial.println(raceId);
}

int deleteAllStoredRaces() {
  if (!sdReady) {
    Serial.println(F("ERROR:SD_NOT_READY"));
    return -1;
  }

  if (loggingState) {
    Serial.println(F("ERROR:BUSY"));
    return -1;
  }

  int deletedCount = 0;

  while (true) {
    char filenameToDelete[16] = "";
    File root = SD.open("/");
    if (!root) {
      Serial.println(F("ERROR:SD_OPEN_FAILED"));
      return -1;
    }

    while (true) {
      File entry = root.openNextFile();
      if (!entry) {
        break;
      }

      const char* entryName = entry.name();
      if (isAnyRaceFilename(entryName)) {
        strncpy(filenameToDelete, entryName, sizeof(filenameToDelete) - 1);
        filenameToDelete[sizeof(filenameToDelete) - 1] = '\0';
        entry.close();
        break;
      }

      entry.close();
    }

    root.close();

    if (filenameToDelete[0] == '\0') {
      break;
    }

    if (!SD.remove(filenameToDelete)) {
      Serial.println(F("ERROR:DELETE_FAILED"));
      return -1;
    }

    deletedCount++;
  }

  Serial.print(F("DELETEALL:OK:"));
  Serial.println(deletedCount);
  return deletedCount;
}

void processCommand(const char* command) {
  if (strcmp(command, "CMD:LIST") == 0) {
    sendRaceList();
    return;
  }

  if (strncmp(command, "CMD:SEND:", 9) == 0) {
    sendRaceFile(command + 9);
    return;
  }

  if (strncmp(command, "ACK:", 4) == 0) {
    acknowledgeRace(command + 4);
    return;
  }

  if (strncmp(command, "CMD:DELETE:", 11) == 0) {
    deleteStoredRace(command + 11);
    return;
  }

  if (strcmp(command, "CMD:DELETE_ALL") == 0) {
    deleteAllStoredRaces();
    return;
  }

  Serial.println(F("ERROR:UNKNOWN_COMMAND"));
}

void handleSerialCommands() {
  while (Serial.available() > 0) {
    const char value = static_cast<char>(Serial.read());
    if (value == '\r') {
      continue;
    }

    if (value == '\n') {
      commandBuffer[commandLength] = '\0';
      if (commandLength > 0) {
        processCommand(commandBuffer);
      }
      commandLength = 0;
      continue;
    }

    if (commandLength < sizeof(commandBuffer) - 1) {
      commandBuffer[commandLength++] = value;
    } else {
      commandLength = 0;
    }
  }
}

void hallISR() {
  count++;
}

void setup() {
  Serial.begin(115200);
  gpsSerial.begin(9600);

  pinMode(hallPin, INPUT_PULLUP);
  pinMode(buttonPin, INPUT_PULLUP);
  pinMode(ledPin, OUTPUT);
  pinMode(chipSelect, OUTPUT);

  attachInterrupt(digitalPinToInterrupt(hallPin), hallISR, FALLING);

  digitalWrite(ledPin, LOW);

  if (SD.begin(chipSelect)) {
    sdReady = true;
    Serial.println(F("SD:READY"));
  } else {
    sdReady = false;
    Serial.println(F("SD:INIT_FAILED"));
  }
}

void loop() {
  while (gpsSerial.available() > 0) {
    gps.encode(gpsSerial.read());
  }

  handleSerialCommands();
  handleButtonState();

  if (loggingState) {
    writeRaceSample(false);
  }

  const unsigned long now = millis();
  sendDashboardState(now);
  sendGpsUpdates(now);
}
