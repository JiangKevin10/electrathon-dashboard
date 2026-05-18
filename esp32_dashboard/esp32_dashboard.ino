#include <Arduino.h>

// Minimal ESP32 dashboard firmware for hall-effect counter bring-up.
// USB serial is used by the Python dashboard. No GPS, SD card, or IMU is required.
const byte hallPin = 25;
const byte buttonPin = 27;
const byte statusLedPin = 26;

const unsigned long dashboardSendInterval = 100;
const unsigned long noFixSendInterval = 2000;
const unsigned long hallPulseDebounceMillis = 500;

volatile unsigned long count = 0;
volatile unsigned long lastHallPulseMillis = 0;
portMUX_TYPE hallCountMux = portMUX_INITIALIZER_UNLOCKED;

bool loggingState = false;
bool lastButtonReading = HIGH;
bool stableButtonState = HIGH;
unsigned long lastDebounceTime = 0;
unsigned long lastDashboardSendTime = 0;
unsigned long lastNoFixSendTime = 0;
char commandBuffer[32] = "";
byte commandLength = 0;

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

bool isPrintableCommandChar(char value) {
  return value >= 32 && value <= 126;
}

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

void processCommand(char* command) {
  trimCommand(command);

  if (strcmp(command, "CMD:IDENTIFY") == 0) {
    Serial.println(F("DEVICE:ESP32"));
    return;
  }

  if (strcmp(command, "CMD:LIST") == 0) {
    Serial.println(F("LIST:BEGIN"));
    Serial.println(F("LIST:END"));
    return;
  }

  if (strcmp(command, "CMD:DELETE_ALL") == 0) {
    Serial.println(F("DELETEALL:BEGIN"));
    Serial.println(F("DELETEALL:OK:0"));
    return;
  }

  if (strncmp(command, "CMD:SEND:", 9) == 0) {
    Serial.println(F("ERROR:RACE_NOT_FOUND"));
    return;
  }

  if (strncmp(command, "CMD:DELETE:", 11) == 0) {
    Serial.print(F("DELETE:OK:"));
    Serial.println(command + 11);
    return;
  }

  if (strncmp(command, "ACK:", 4) == 0) {
    Serial.print(F("ACK:OK:"));
    Serial.println(command + 4);
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

void sendDashboardState(unsigned long now) {
  if (now - lastDashboardSendTime < dashboardSendInterval) {
    return;
  }

  Serial.print(F("COUNT:"));
  Serial.println(readHallCount());

  Serial.print(F("LOG:"));
  Serial.println(loggingState ? 1 : 0);

  Serial.println(F("RACEFILE:"));

  lastDashboardSendTime = now;
}

void sendUnavailableSensors(unsigned long now) {
  if (now - lastNoFixSendTime < noFixSendInterval) {
    return;
  }

  Serial.println(F("GPS:NOFIX"));
  Serial.println(F("GPSTIME:NOFIX"));
  Serial.println(F("IMU:NOIMU"));
  lastNoFixSendTime = now;
}

void handleButtonState() {
  const bool reading = digitalRead(buttonPin);

  if (reading != lastButtonReading) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > 50) {
    if (reading != stableButtonState) {
      stableButtonState = reading;
      if (stableButtonState == LOW) {
        loggingState = !loggingState;
        digitalWrite(statusLedPin, loggingState ? HIGH : LOW);
        if (loggingState) {
          resetHallCount();
        }
      }
    }
  }

  lastButtonReading = reading;
}

void IRAM_ATTR hallISR() {
  const unsigned long now = millis();
  portENTER_CRITICAL_ISR(&hallCountMux);
  if (now - lastHallPulseMillis >= hallPulseDebounceMillis) {
    count++;
    lastHallPulseMillis = now;
  }
  portEXIT_CRITICAL_ISR(&hallCountMux);
}

void setup() {
  Serial.begin(115200);

  pinMode(hallPin, INPUT_PULLUP);
  pinMode(buttonPin, INPUT_PULLUP);
  pinMode(statusLedPin, OUTPUT);
  digitalWrite(statusLedPin, LOW);

  attachInterrupt(digitalPinToInterrupt(hallPin), hallISR, FALLING);

  Serial.println(F("DEVICE:ESP32"));
  Serial.println(F("HALL:READY"));
}

void loop() {
  const unsigned long now = millis();

  handleSerialCommands();
  handleButtonState();
  sendDashboardState(now);
  sendUnavailableSensors(now);
}
