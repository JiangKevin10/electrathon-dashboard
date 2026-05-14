#include <Arduino.h>
#include <SPI.h>
#include <SparkFun_BNO08x_Arduino_Library.h>

// ESP32-only BNO08X SPI wiring test.
//
// Wiring from WIRING_GUIDE.md:
// - GY-BNO08X SCL/SCK -> GPIO18
// - GY-BNO08X SDA/MISO -> GPIO19
// - GY-BNO08X ADO/MOSI -> GPIO23
// - GY-BNO08X CS -> GPIO14
// - GY-BNO08X INT -> GPIO33
// - GY-BNO08X RST -> GPIO32
// - GY-BNO08X PS0 -> 3V3
// - GY-BNO08X PS1 -> 3V3
// - GY-BNO08X VCC -> 3V3
// - GY-BNO08X GND -> GND
//
// Install this Arduino library first:
// SparkFun BNO08x Arduino Library
//
// Open Serial Monitor at 115200 baud.

const uint8_t imuSckPin = 18;
const uint8_t imuMisoPin = 19;
const uint8_t imuMosiPin = 23;
const uint8_t imuCsPin = 14;
const uint8_t imuIntPin = 33;
const uint8_t imuRstPin = 32;

const unsigned long reportIntervalMs = 250;
const unsigned long reconnectIntervalMs = 5000;
const uint32_t imuSpiSpeedHz = 400000;

BNO08x imu;

enum ImuReportMode {
  REPORT_NONE,
  REPORT_ROTATION_VECTOR,
  REPORT_GAME_ROTATION_VECTOR,
  REPORT_ACCELEROMETER
};

bool imuReady = false;
ImuReportMode reportMode = REPORT_NONE;
unsigned long lastReportTime = 0;
unsigned long lastReconnectAttempt = 0;

float radiansToDegrees(float radians) {
  return radians * 180.0f / PI;
}

float quaternionYaw(float real, float i, float j, float k) {
  return atan2f(2.0f * (real * k + i * j), 1.0f - 2.0f * (j * j + k * k));
}

float quaternionPitch(float real, float i, float j, float k) {
  const float value = 2.0f * (real * j - k * i);
  return asinf(constrain(value, -1.0f, 1.0f));
}

float quaternionRoll(float real, float i, float j, float k) {
  return atan2f(2.0f * (real * i + j * k), 1.0f - 2.0f * (i * i + j * j));
}

void printPins() {
  Serial.println(F("ESP32 BNO08X SPI test"));
  Serial.println(F("Serial monitor: 115200 baud"));
  Serial.println(F("Expected wiring:"));
  Serial.println(F("  SCL/SCK -> GPIO18"));
  Serial.println(F("  SDA/MISO -> GPIO19"));
  Serial.println(F("  ADO/MOSI -> GPIO23"));
  Serial.println(F("  CS -> GPIO14"));
  Serial.println(F("  INT -> GPIO33"));
  Serial.println(F("  RST -> GPIO32"));
  Serial.println(F("  PS0 -> 3V3"));
  Serial.println(F("  PS1 -> 3V3"));
  Serial.println(F("  VCC -> 3V3"));
  Serial.println(F("  GND -> GND"));
}

bool startImu() {
  reportMode = REPORT_NONE;
  Serial.println(F("IMU:BEGIN"));

  pinMode(imuCsPin, OUTPUT);
  digitalWrite(imuCsPin, HIGH);
  pinMode(imuRstPin, OUTPUT);
  digitalWrite(imuRstPin, HIGH);
  SPI.begin(imuSckPin, imuMisoPin, imuMosiPin, imuCsPin);
  delay(250);

  if (!imu.beginSPI(imuCsPin, imuIntPin, imuRstPin, imuSpiSpeedHz)) {
    Serial.println(F("IMU:NOT_FOUND"));
    Serial.println(F("Check power, common ground, SPI wires, CS/INT/RST, and PS0/PS1 tied high."));
    return false;
  }

  Serial.println(F("IMU:FOUND"));
  delay(500);

  if (imu.enableRotationVector(50)) {
    reportMode = REPORT_ROTATION_VECTOR;
    Serial.println(F("IMU:ROTATION_VECTOR_READY"));
    Serial.println(F("Format: IMU:heading_deg,pitch_deg,roll_deg,accuracy_rad"));
    delay(100);
    return true;
  }

  Serial.println(F("IMU:ROTATION_VECTOR_ENABLE_FAILED"));

  if (imu.enableGameRotationVector(50)) {
    reportMode = REPORT_GAME_ROTATION_VECTOR;
    Serial.println(F("IMU:GAME_ROTATION_VECTOR_READY"));
    Serial.println(F("Format: IMU:heading_deg,pitch_deg,roll_deg,accuracy_rad"));
    delay(100);
    return true;
  }

  Serial.println(F("IMU:GAME_ROTATION_VECTOR_ENABLE_FAILED"));

  if (imu.enableAccelerometer(50)) {
    reportMode = REPORT_ACCELEROMETER;
    Serial.println(F("IMU:ACCELEROMETER_READY"));
    Serial.println(F("Format: IMU_ACCEL:x_g,y_g,z_g"));
    delay(100);
    return true;
  }

  Serial.println(F("IMU:ACCELEROMETER_ENABLE_FAILED"));
  Serial.println(F("IMU:FOUND_BUT_NO_REPORTS"));
  Serial.println(F("Power-cycle the ESP32 and IMU, then try again. Keep SPI wires short."));
  return false;
}

void setup() {
  Serial.begin(115200);
  delay(1500);

  printPins();
  imuReady = startImu();
  lastReconnectAttempt = millis();
}

void loop() {
  const unsigned long now = millis();

  if (!imuReady) {
    if (now - lastReconnectAttempt >= reconnectIntervalMs) {
      lastReconnectAttempt = now;
      imuReady = startImu();
    }
    return;
  }

  if (imu.wasReset()) {
    Serial.println(F("IMU:RESET_DETECTED"));
    imuReady = startImu();
    return;
  }

  if (!imu.getSensorEvent()) {
    return;
  }

  if (now - lastReportTime < reportIntervalMs) {
    return;
  }
  lastReportTime = now;

  const uint8_t eventId = imu.getSensorEventID();

  if (reportMode == REPORT_ROTATION_VECTOR && eventId == SENSOR_REPORTID_ROTATION_VECTOR) {
    const float quatI = imu.getQuatI();
    const float quatJ = imu.getQuatJ();
    const float quatK = imu.getQuatK();
    const float quatReal = imu.getQuatReal();
    const float accuracy = imu.getQuatRadianAccuracy();

    const float headingDeg = radiansToDegrees(quaternionYaw(quatReal, quatI, quatJ, quatK));
    const float pitchDeg = radiansToDegrees(quaternionPitch(quatReal, quatI, quatJ, quatK));
    const float rollDeg = radiansToDegrees(quaternionRoll(quatReal, quatI, quatJ, quatK));

    Serial.print(F("IMU:"));
    Serial.print(headingDeg, 2);
    Serial.print(',');
    Serial.print(pitchDeg, 2);
    Serial.print(',');
    Serial.print(rollDeg, 2);
    Serial.print(',');
    Serial.println(accuracy, 4);
    return;
  }

  if (reportMode == REPORT_GAME_ROTATION_VECTOR && eventId == SENSOR_REPORTID_GAME_ROTATION_VECTOR) {
    const float quatI = imu.getGameQuatI();
    const float quatJ = imu.getGameQuatJ();
    const float quatK = imu.getGameQuatK();
    const float quatReal = imu.getGameQuatReal();

    const float headingDeg = radiansToDegrees(quaternionYaw(quatReal, quatI, quatJ, quatK));
    const float pitchDeg = radiansToDegrees(quaternionPitch(quatReal, quatI, quatJ, quatK));
    const float rollDeg = radiansToDegrees(quaternionRoll(quatReal, quatI, quatJ, quatK));

    Serial.print(F("IMU_GAME:"));
    Serial.print(headingDeg, 2);
    Serial.print(',');
    Serial.print(pitchDeg, 2);
    Serial.print(',');
    Serial.print(rollDeg, 2);
    Serial.println(F(",0.0000"));
    return;
  }

  if (reportMode == REPORT_ACCELEROMETER && eventId == SENSOR_REPORTID_ACCELEROMETER) {
    Serial.print(F("IMU_ACCEL:"));
    Serial.print(imu.getAccelX(), 4);
    Serial.print(',');
    Serial.print(imu.getAccelY(), 4);
    Serial.print(',');
    Serial.println(imu.getAccelZ(), 4);
  }
}
