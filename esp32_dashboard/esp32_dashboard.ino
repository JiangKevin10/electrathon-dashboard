#include <Arduino.h>
#include <FS.h>
#include <SPI.h>
#include <SD.h>
#include <TinyGPS++.h>
#include <string.h>

// ESP32 dashboard firmware: full feature parity with arudino.ino but adapted
// for the ESP32 pinout and core (HardwareSerial UART2 for GPS, SPI SD card,
// IRAM_ATTR ISR with portMUX, IDENTIFY response). The Python dashboard
// (serial_worker.py) talks to this firmware over USB at 115200.

// ---- Pin map (matches WIRING_GUIDE.md / esp32_bringup_test) ----
const uint8_t hallPin = 25;
const uint8_t buttonPin = 27;
const uint8_t statusLedPin = 26;
const uint8_t gpsRxPin = 16;  // ESP32 RX  <-  GPS TX
const uint8_t gpsTxPin = 17;  // ESP32 TX  ->  GPS RX

const uint8_t sdSckPin = 18;
const uint8_t sdMisoPin = 19;
const uint8_t sdMosiPin = 23;
const uint8_t sdChipSelectPin = 5;

// ---- Timing constants ----
const unsigned long debounceDelay = 50;
const unsigned long dashboardSendInterval = 100;
const unsigned long gpsNoFixReportInterval = 2000;
const unsigned long rawLogWriteInterval = 500;
const unsigned long backgroundTelemetryInterval = 250;
const unsigned long imuHeartbeatInterval = 2000;
const unsigned long hallPulseDebounceMillis = 5;
const uint8_t syncedRaceRetentionCount = 5;

// ---- Globals ----
HardwareSerial gpsSerial(2);
TinyGPSPlus gps;
File raceFile;

volatile unsigned long count = 0;
volatile unsigned long lastHallPulseMillis = 0;
portMUX_TYPE hallCountMux = portMUX_INITIALIZER_UNLOCKED;

bool sdReady = false;
bool loggingState = false;
bool lastButtonReading = HIGH;
bool stableButtonState = HIGH;

unsigned long lastDebounceTime = 0;
unsigned long lastDashboardSendTime = 0;
unsigned long lastGpsNoFixReportTime = 0;
unsigned long lastGpsRxReportTime = 0;
unsigned long lastRawLogTime = 0;
unsigned long lastBackgroundTelemetryTime = 0;
unsigned long lastImuHeartbeatTime = 0;
unsigned long raceStartMillis = 0;
unsigned long raceStartCount = 0;
unsigned long gpsBytesReceived = 0;

char currentRaceFilename[12] = "";  // e.g. "R000001.CSV"
char commandBuffer[64] = "";
uint8_t commandLength = 0;

// ---- Hall counter helpers ----
void IRAM_ATTR hallISR() {
  const unsigned long now = millis();
  portENTER_CRITICAL_ISR(&hallCountMux);
  if (now - lastHallPulseMillis >= hallPulseDebounceMillis) {
    count++;
    lastHallPulseMillis = now;
  }
  portEXIT_CRITICAL_ISR(&hallCountMux);
}

unsigned long readHallCount() {
  portENTER_CRITICAL(&hallCountMux);
  const unsigned long snapshot = count;
  portEXIT_CRITICAL(&hallCountMux);
  return snapshot;
}

void resetHallCount() {
  portENTER_CRITICAL(&hallCountMux);
  count = 0;
  lastHallPulseMillis = millis();
  portEXIT_CRITICAL(&hallCountMux);
}

// ---- Filename helpers ----
bool isDigitChar(char value) {
  return value >= '0' && value <= '9';
}

bool isPrintableCommandChar(char value) {
  return value >= 32 && value <= 126;
}

// Strip a single leading '/' that the ESP32 SD library may include.
const char* stripLeadingSlash(const char* name) {
  if (name && name[0] == '/') {
    return name + 1;
  }
  return name;
}

// Build "/Rxxxxxx.CSV" from "Rxxxxxx.CSV".
void buildSdPath(char* outBuffer, size_t outSize, const char* filename) {
  if (!filename) {
    if (outSize > 0) {
      outBuffer[0] = '\0';
    }
    return;
  }
  if (filename[0] == '/') {
    strncpy(outBuffer, filename, outSize - 1);
  } else {
    snprintf(outBuffer, outSize, "/%s", filename);
  }
  outBuffer[outSize - 1] = '\0';
}

bool isRaceFilename(const char* filename, char prefix) {
  const char* name = stripLeadingSlash(filename);
  if (!name || strlen(name) != 11) {
    return false;
  }

  if (name[0] != prefix || name[7] != '.') {
    return false;
  }

  for (uint8_t index = 1; index <= 6; index++) {
    if (!isDigitChar(name[index])) {
      return false;
    }
  }

  return name[8] == 'C' && name[9] == 'S' && name[10] == 'V';
}

bool isAnyRaceFilename(const char* filename) {
  return isRaceFilename(filename, 'R') || isRaceFilename(filename, 'S');
}

unsigned long extractRaceSequence(const char* filename) {
  if (!isAnyRaceFilename(filename)) {
    return 0;
  }

  const char* name = stripLeadingSlash(filename);
  unsigned long value = 0;
  for (uint8_t index = 1; index <= 6; index++) {
    value = (value * 10UL) + static_cast<unsigned long>(name[index] - '0');
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
  char sourcePath[16];
  char targetPath[16];
  buildSdPath(sourcePath, sizeof(sourcePath), sourceName);
  buildSdPath(targetPath, sizeof(targetPath), targetName);

  File sourceFile = SD.open(sourcePath, FILE_READ);
  if (!sourceFile) {
    return false;
  }

  if (SD.exists(targetPath)) {
    SD.remove(targetPath);
  }

  File targetFile = SD.open(targetPath, FILE_WRITE);
  if (!targetFile) {
    sourceFile.close();
    return false;
  }

  uint8_t copyBuffer[64];
  while (sourceFile.available()) {
    const int bytesRead = sourceFile.read(copyBuffer, sizeof(copyBuffer));
    if (bytesRead <= 0) {
      break;
    }
    targetFile.write(copyBuffer, bytesRead);
  }

  targetFile.flush();
  sourceFile.close();
  targetFile.close();
  return true;
}

void pruneSyncedRaces() {
  while (true) {
    uint8_t syncedCount = 0;
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

      const char* entryName = stripLeadingSlash(entry.name());
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

    char oldestPath[16];
    buildSdPath(oldestPath, sizeof(oldestPath), oldestFilename);
    SD.remove(oldestPath);
  }
}

// ---- GPS reporting ----
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

  char buffer[24];
  snprintf(
    buffer,
    sizeof(buffer),
    "GPSTIME:%04d-%02d-%02d,%02d:%02d:%02d",
    gps.date.year(),
    gps.date.month(),
    gps.date.day(),
    gps.time.hour(),
    gps.time.minute(),
    gps.time.second()
  );
  Serial.println(buffer);
}

void formatGpsDate(char* buffer, size_t size) {
  if (!gps.date.isValid()) {
    if (size > 0) {
      buffer[0] = '\0';
    }
    return;
  }
  snprintf(buffer, size, "%04d-%02d-%02d", gps.date.year(), gps.date.month(), gps.date.day());
}

void formatGpsTime(char* buffer, size_t size) {
  if (!gps.time.isValid()) {
    if (size > 0) {
      buffer[0] = '\0';
    }
    return;
  }
  snprintf(buffer, size, "%02d:%02d:%02d", gps.time.hour(), gps.time.minute(), gps.time.second());
}

// ---- Race logging ----
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

  char racePath[16];
  buildSdPath(racePath, sizeof(racePath), currentRaceFilename);

  // FILE_APPEND on ESP32 creates the file if it does not exist and positions
  // at the end. Since we just generated a fresh sequence number it should be
  // a new empty file, so the header lands at the start.
  raceFile = SD.open(racePath, FILE_APPEND);
  if (!raceFile) {
    currentRaceFilename[0] = '\0';
    Serial.println(F("ERROR:RACE_OPEN_FAILED"));
    return false;
  }

  raceFile.println("elapsed_ms,count,latitude,longitude,gps_fix,gps_satellites,gps_utc_date,gps_utc_time");
  raceFile.flush();

  resetHallCount();
  raceStartMillis = millis();
  raceStartCount = 0;
  lastRawLogTime = 0;
  loggingState = true;
  digitalWrite(statusLedPin, HIGH);
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
  digitalWrite(statusLedPin, LOW);
  resetHallCount();
  raceStartCount = 0;
  Serial.println(F("RACEFILE:"));
}

// ---- Button handling ----
void handleButtonState() {
  const bool reading = digitalRead(buttonPin);

  if (reading != lastButtonReading) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (reading != stableButtonState) {
      stableButtonState = reading;
      Serial.print(F("BUTTON:"));
      Serial.println(stableButtonState == LOW ? F("DOWN") : F("UP"));
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

// ---- Periodic telemetry ----
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

  if (now - lastGpsRxReportTime >= gpsNoFixReportInterval) {
    Serial.print(F("GPSRX:"));
    Serial.println(gpsBytesReceived);
    lastGpsRxReportTime = now;
  }
}

void sendImuHeartbeat(unsigned long now) {
  // No IMU is wired into this firmware build; emit NOIMU on a slow cadence so
  // the dashboard can clear stale state.
  if (now - lastImuHeartbeatTime < imuHeartbeatInterval) {
    return;
  }
  Serial.println(F("IMU:NOIMU"));
  lastImuHeartbeatTime = now;
}

void serviceGpsInput() {
  while (gpsSerial.available() > 0) {
    gps.encode(gpsSerial.read());
    gpsBytesReceived++;
  }
}

void serviceBackgroundTelemetry() {
  const unsigned long now = millis();
  if (now - lastBackgroundTelemetryTime < backgroundTelemetryInterval) {
    return;
  }

  sendDashboardState(now);
  sendGpsUpdates(now);
  sendImuHeartbeat(now);
  lastBackgroundTelemetryTime = now;
}

// ---- Stored race commands ----
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

      const char* entryName = stripLeadingSlash(entry.name());
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

  char racePath[16];
  buildSdPath(racePath, sizeof(racePath), raceId);

  File file = SD.open(racePath, FILE_READ);
  if (!file) {
    Serial.println(F("ERROR:RACE_NOT_FOUND"));
    return;
  }

  Serial.print(F("FILE:BEGIN:"));
  Serial.print(raceId);
  Serial.write(',');
  Serial.println(file.size());

  char lineBuffer[96];
  uint8_t lineLength = 0;
  while (file.available()) {
    serviceGpsInput();
    const int rawValue = file.read();
    if (rawValue < 0) {
      break;
    }
    const char value = static_cast<char>(rawValue);
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

    serviceBackgroundTelemetry();
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

  char racePath[16];
  char syncedPath[16];
  buildSdPath(racePath, sizeof(racePath), raceId);
  buildSdPath(syncedPath, sizeof(syncedPath), syncedFilename);

  if (!SD.exists(racePath)) {
    if (SD.exists(syncedPath)) {
      Serial.print(F("ACK:OK:"));
      Serial.println(raceId);
      return;
    }

    Serial.println(F("ERROR:RACE_NOT_FOUND"));
    return;
  }

  if (!copyFile(raceId, syncedFilename)) {
    Serial.println(F("ERROR:SYNC_MARK_FAILED"));
    return;
  }

  if (!SD.remove(racePath)) {
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

  char racePath[16];
  buildSdPath(racePath, sizeof(racePath), raceId);

  if (!SD.exists(racePath)) {
    Serial.print(F("DELETE:OK:"));
    Serial.println(raceId);
    return;
  }

  if (!SD.remove(racePath)) {
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
  Serial.println(F("DELETEALL:BEGIN"));

  while (true) {
    char filenameToDelete[16] = "";
    serviceGpsInput();
    serviceBackgroundTelemetry();
    File root = SD.open("/");
    if (!root) {
      Serial.println(F("ERROR:SD_OPEN_FAILED"));
      return -1;
    }

    while (true) {
      serviceGpsInput();
      File entry = root.openNextFile();
      if (!entry) {
        break;
      }

      const char* entryName = stripLeadingSlash(entry.name());
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

    char victimPath[16];
    buildSdPath(victimPath, sizeof(victimPath), filenameToDelete);
    if (!SD.remove(victimPath)) {
      Serial.println(F("ERROR:DELETE_FAILED"));
      return -1;
    }

    deletedCount++;
    serviceBackgroundTelemetry();
    Serial.print(F("DELETEALL:PROGRESS:"));
    Serial.println(deletedCount);
  }

  Serial.print(F("DELETEALL:OK:"));
  Serial.println(deletedCount);
  return deletedCount;
}

// ---- Command parsing ----
void trimCommand(char* command) {
  while (command[0] == ' ' || command[0] == '\t') {
    memmove(command, command + 1, strlen(command));
  }

  size_t length = strlen(command);
  while (length > 0 && (command[length - 1] == ' ' || command[length - 1] == '\t')) {
    command[length - 1] = '\0';
    length--;
  }
}

void alignCommandPrefix(char* command) {
  char* cmdStart = strstr(command, "CMD:");
  char* ackStart = strstr(command, "ACK:");
  char* prefixStart = nullptr;

  if (cmdStart && ackStart) {
    prefixStart = (cmdStart < ackStart) ? cmdStart : ackStart;
  } else if (cmdStart) {
    prefixStart = cmdStart;
  } else if (ackStart) {
    prefixStart = ackStart;
  }

  if (prefixStart && prefixStart != command) {
    memmove(command, prefixStart, strlen(prefixStart) + 1);
  }
}

void processCommand(char* command) {
  trimCommand(command);
  alignCommandPrefix(command);
  trimCommand(command);

  if (strcmp(command, "CMD:IDENTIFY") == 0) {
    Serial.println(F("DEVICE:ESP32"));
    return;
  }

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

  Serial.print(F("ERROR:UNKNOWN_COMMAND:"));
  Serial.println(command);
}

void handleSerialCommands() {
  while (Serial.available() > 0) {
    const char value = static_cast<char>(Serial.read());
    if (value == '\r') {
      continue;
    }

    if (!isPrintableCommandChar(value) && value != '\n') {
      commandLength = 0;
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

// ---- Setup / loop ----
void setup() {
  Serial.begin(115200);
  gpsSerial.begin(9600, SERIAL_8N1, gpsRxPin, gpsTxPin);

  pinMode(hallPin, INPUT_PULLUP);
  pinMode(buttonPin, INPUT_PULLUP);
  pinMode(statusLedPin, OUTPUT);
  pinMode(sdChipSelectPin, OUTPUT);
  digitalWrite(statusLedPin, LOW);
  digitalWrite(sdChipSelectPin, HIGH);

  attachInterrupt(digitalPinToInterrupt(hallPin), hallISR, FALLING);

  Serial.println(F("DEVICE:ESP32"));

  SPI.begin(sdSckPin, sdMisoPin, sdMosiPin, sdChipSelectPin);
  if (SD.begin(sdChipSelectPin, SPI)) {
    sdReady = true;
    Serial.println(F("SD:READY"));
  } else {
    sdReady = false;
    Serial.println(F("SD:INIT_FAILED"));
  }
}

void loop() {
  serviceGpsInput();

  handleSerialCommands();
  handleButtonState();

  if (loggingState) {
    writeRaceSample(false);
  }

  const unsigned long now = millis();
  sendDashboardState(now);
  sendGpsUpdates(now);
  sendImuHeartbeat(now);
}
