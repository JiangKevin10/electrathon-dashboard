#include <Arduino.h>
#include <FS.h>
#include <SPI.h>
#include <SD.h>

// SD card storage reference — extracted from esp32_dashboard.ino.
// Shows how race files are created, written, listed, synced, and deleted
// on an ESP32 with a SPI microSD adapter (SCK=18, MISO=19, MOSI=23, CS=5).
//
// Race files are named R000001.CSV, R000002.CSV, etc.
// When a race is acknowledged (synced to PC), it is renamed to S000001.CSV.
// Only the 5 most recent synced races are kept; older ones are pruned.

// ---- Pin map ----
const uint8_t sdSckPin        = 18;
const uint8_t sdMisoPin       = 19;
const uint8_t sdMosiPin       = 23;
const uint8_t sdChipSelectPin = 5;

// ---- Config ----
const uint8_t       syncedRaceRetentionCount = 5;
const unsigned long rawLogWriteInterval      = 500;  // ms between CSV rows

// ---- State ----
bool          sdReady             = false;
File          raceFile;
char          currentRaceFilename[12] = "";  // "R000001.CSV"
unsigned long lastRawLogTime      = 0;
unsigned long raceStartMillis     = 0;

// ---- SD init ----
// Call once from setup(). Tries 400kHz for SanDisk compatibility.
void sdBegin() {
  delay(500);  // allow card to power up before touching SPI
  SPI.begin(sdSckPin, sdMisoPin, sdMosiPin, sdChipSelectPin);
  delay(100);
  if (SD.begin(sdChipSelectPin, SPI, 400000)) {
    sdReady = true;
    Serial.println("SD:READY");
  } else {
    sdReady = false;
    Serial.println("SD:INIT_FAILED");
  }
}

// ---- Filename helpers ----
const char* stripLeadingSlash(const char* name) {
  if (name && name[0] == '/') return name + 1;
  return name;
}

void buildSdPath(char* outBuffer, size_t outSize, const char* filename) {
  if (!filename) { if (outSize > 0) outBuffer[0] = '\0'; return; }
  if (filename[0] == '/') {
    strncpy(outBuffer, filename, outSize - 1);
  } else {
    snprintf(outBuffer, outSize, "/%s", filename);
  }
  outBuffer[outSize - 1] = '\0';
}

// Returns true if filename matches the pattern X000000.CSV where X is prefix.
bool isRaceFilename(const char* filename, char prefix) {
  const char* name = stripLeadingSlash(filename);
  if (!name || strlen(name) != 11) return false;
  if (name[0] != prefix || name[7] != '.') return false;
  for (uint8_t i = 1; i <= 6; i++) {
    if (name[i] < '0' || name[i] > '9') return false;
  }
  return name[8] == 'C' && name[9] == 'S' && name[10] == 'V';
}

bool isAnyRaceFilename(const char* filename) {
  return isRaceFilename(filename, 'R') || isRaceFilename(filename, 'S');
}

unsigned long extractRaceSequence(const char* filename) {
  if (!isAnyRaceFilename(filename)) return 0;
  const char* name = stripLeadingSlash(filename);
  unsigned long value = 0;
  for (uint8_t i = 1; i <= 6; i++) {
    value = (value * 10UL) + (unsigned long)(name[i] - '0');
  }
  return value;
}

// Scans SD root and returns the next unused sequence number.
unsigned long findNextRaceSequence() {
  unsigned long maxSequence = 0;
  File root = SD.open("/");
  if (!root) return 1;
  while (true) {
    File entry = root.openNextFile();
    if (!entry) break;
    unsigned long seq = extractRaceSequence(entry.name());
    if (seq > maxSequence) maxSequence = seq;
    entry.close();
  }
  root.close();
  return maxSequence + 1;
}

// ---- File operations ----
bool copyFile(const char* sourceName, const char* targetName) {
  char sourcePath[16], targetPath[16];
  buildSdPath(sourcePath, sizeof(sourcePath), sourceName);
  buildSdPath(targetPath, sizeof(targetPath), targetName);

  File src = SD.open(sourcePath, FILE_READ);
  if (!src) return false;
  if (SD.exists(targetPath)) SD.remove(targetPath);
  File dst = SD.open(targetPath, FILE_WRITE);
  if (!dst) { src.close(); return false; }

  uint8_t buf[64];
  while (src.available()) {
    int n = src.read(buf, sizeof(buf));
    if (n <= 0) break;
    dst.write(buf, n);
  }
  dst.flush();
  src.close();
  dst.close();
  return true;
}

// Deletes the oldest synced race if more than syncedRaceRetentionCount exist.
void pruneSyncedRaces() {
  while (true) {
    uint8_t syncedCount = 0;
    unsigned long oldestSeq = 0;
    char oldestName[16] = "";

    File root = SD.open("/");
    if (!root) return;
    while (true) {
      File entry = root.openNextFile();
      if (!entry) break;
      const char* name = stripLeadingSlash(entry.name());
      if (isRaceFilename(name, 'S')) {
        syncedCount++;
        unsigned long seq = extractRaceSequence(name);
        if (oldestSeq == 0 || seq < oldestSeq) {
          oldestSeq = seq;
          strncpy(oldestName, name, sizeof(oldestName) - 1);
          oldestName[sizeof(oldestName) - 1] = '\0';
        }
      }
      entry.close();
    }
    root.close();

    if (syncedCount <= syncedRaceRetentionCount || oldestName[0] == '\0') return;
    char path[16];
    buildSdPath(path, sizeof(path), oldestName);
    SD.remove(path);
  }
}

// ---- Race logging ----
bool startRaceLogging() {
  if (!sdReady) { Serial.println("ERROR:SD_NOT_READY"); return false; }

  unsigned long seq = findNextRaceSequence();
  snprintf(currentRaceFilename, sizeof(currentRaceFilename), "R%06lu.CSV", seq);

  char path[16];
  buildSdPath(path, sizeof(path), currentRaceFilename);

  raceFile = SD.open(path, FILE_APPEND);
  if (!raceFile) {
    currentRaceFilename[0] = '\0';
    Serial.println("ERROR:RACE_OPEN_FAILED");
    return false;
  }

  raceFile.println("elapsed_ms,count,latitude,longitude,gps_fix,gps_satellites,gps_utc_date,gps_utc_time");
  raceFile.flush();

  raceStartMillis = millis();
  lastRawLogTime  = 0;
  Serial.print("RACEFILE:");
  Serial.println(currentRaceFilename);
  return true;
}

void stopRaceLogging() {
  if (raceFile) {
    raceFile.flush();
    raceFile.close();
  }
  Serial.println("RACEFILE:");
}

// Call repeatedly from loop() while a race is active.
// Pass forceWrite=true to flush immediately regardless of interval.
void writeRaceSample(unsigned long elapsedMs, unsigned long hallCount,
                     bool hasFix, double lat, double lng,
                     uint8_t sats, const char* gpsDate, const char* gpsTime,
                     bool forceWrite) {
  if (!raceFile) return;
  unsigned long now = millis();
  if (!forceWrite && (now - lastRawLogTime) < rawLogWriteInterval) return;

  raceFile.print(elapsedMs);  raceFile.print(",");
  raceFile.print(hallCount);  raceFile.print(",");
  if (hasFix) raceFile.print(lat, 6); raceFile.print(",");
  if (hasFix) raceFile.print(lng, 6); raceFile.print(",");
  raceFile.print(hasFix ? 1 : 0);    raceFile.print(",");
  raceFile.print(sats);               raceFile.print(",");
  raceFile.print(gpsDate);            raceFile.print(",");
  raceFile.println(gpsTime);
  raceFile.flush();
  lastRawLogTime = now;
}

// ---- Race file commands (called by serial command handler) ----
void sendRaceList() {
  if (!sdReady) { Serial.println("ERROR:SD_NOT_READY"); return; }

  Serial.println("LIST:BEGIN");
  File root = SD.open("/");
  if (root) {
    while (true) {
      File entry = root.openNextFile();
      if (!entry) break;
      const char* name = stripLeadingSlash(entry.name());
      if (isRaceFilename(name, 'R')) {
        Serial.print("LIST:ITEM:");
        Serial.print(name);
        Serial.print(",");
        Serial.println(entry.size());
      }
      entry.close();
    }
    root.close();
  }
  Serial.println("LIST:END");
}

void sendRaceFile(const char* raceId) {
  if (!sdReady)                        { Serial.println("ERROR:SD_NOT_READY");    return; }
  if (!isRaceFilename(raceId, 'R'))    { Serial.println("ERROR:INVALID_RACE_ID"); return; }

  char path[16];
  buildSdPath(path, sizeof(path), raceId);
  File file = SD.open(path, FILE_READ);
  if (!file) { Serial.println("ERROR:RACE_NOT_FOUND"); return; }

  Serial.print("FILE:BEGIN:");
  Serial.print(raceId);
  Serial.print(",");
  Serial.println(file.size());

  char lineBuf[96];
  uint8_t lineLen = 0;
  while (file.available()) {
    int raw = file.read();
    if (raw < 0) break;
    char c = (char)raw;
    if (c == '\r') continue;
    if (c == '\n') {
      lineBuf[lineLen] = '\0';
      Serial.print("FILE:DATA:");
      Serial.println(lineBuf);
      lineLen = 0;
      continue;
    }
    if (lineLen < sizeof(lineBuf) - 1) lineBuf[lineLen++] = c;
  }
  if (lineLen > 0) {
    lineBuf[lineLen] = '\0';
    Serial.print("FILE:DATA:");
    Serial.println(lineBuf);
  }
  file.close();
  Serial.print("FILE:END:");
  Serial.println(raceId);
}

// Marks a race as synced by renaming R→S, then prunes old synced files.
void acknowledgeRace(const char* raceId) {
  if (!sdReady)                     { Serial.println("ERROR:SD_NOT_READY");    return; }
  if (!isRaceFilename(raceId, 'R')) { Serial.println("ERROR:INVALID_RACE_ID"); return; }

  char syncedName[16];
  strncpy(syncedName, raceId, sizeof(syncedName) - 1);
  syncedName[sizeof(syncedName) - 1] = '\0';
  syncedName[0] = 'S';

  char racePath[16], syncedPath[16];
  buildSdPath(racePath,   sizeof(racePath),   raceId);
  buildSdPath(syncedPath, sizeof(syncedPath), syncedName);

  if (!SD.exists(racePath)) {
    if (SD.exists(syncedPath)) { Serial.print("ACK:OK:"); Serial.println(raceId); return; }
    Serial.println("ERROR:RACE_NOT_FOUND");
    return;
  }

  if (!copyFile(raceId, syncedName))  { Serial.println("ERROR:SYNC_MARK_FAILED");   return; }
  if (!SD.remove(racePath))           { Serial.println("ERROR:SYNC_REMOVE_FAILED"); return; }

  pruneSyncedRaces();
  Serial.print("ACK:OK:");
  Serial.println(raceId);
}

void deleteStoredRace(const char* raceId) {
  if (!sdReady)                      { Serial.println("ERROR:SD_NOT_READY");    return; }
  if (!isAnyRaceFilename(raceId))    { Serial.println("ERROR:INVALID_RACE_ID"); return; }

  char path[16];
  buildSdPath(path, sizeof(path), raceId);
  if (!SD.exists(path)) { Serial.print("DELETE:OK:"); Serial.println(raceId); return; }
  if (!SD.remove(path)) { Serial.println("ERROR:DELETE_FAILED"); return; }
  Serial.print("DELETE:OK:");
  Serial.println(raceId);
}

int deleteAllStoredRaces() {
  if (!sdReady) { Serial.println("ERROR:SD_NOT_READY"); return -1; }

  int deleted = 0;
  Serial.println("DELETEALL:BEGIN");

  while (true) {
    char toDelete[16] = "";

    File root = SD.open("/");
    if (!root) { Serial.println("ERROR:SD_OPEN_FAILED"); return -1; }
    while (true) {
      File entry = root.openNextFile();
      if (!entry) break;
      const char* name = stripLeadingSlash(entry.name());
      if (isAnyRaceFilename(name)) {
        strncpy(toDelete, name, sizeof(toDelete) - 1);
        toDelete[sizeof(toDelete) - 1] = '\0';
        entry.close();
        break;
      }
      entry.close();
    }
    root.close();

    if (toDelete[0] == '\0') break;

    char path[16];
    buildSdPath(path, sizeof(path), toDelete);
    if (!SD.remove(path)) { Serial.println("ERROR:DELETE_FAILED"); return -1; }

    deleted++;
    Serial.print("DELETEALL:PROGRESS:");
    Serial.println(deleted);
  }

  Serial.print("DELETEALL:OK:");
  Serial.println(deleted);
  return deleted;
}

// ---- Minimal setup/loop to compile standalone ----
void setup() {
  Serial.begin(115200);
  sdBegin();
}

void loop() {}
