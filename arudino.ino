const int hallPin = 2;
const int buttonPin = 4;
const int ledPin = 7;

volatile unsigned long count = 0;

bool loggingState = false;

bool lastButtonReading = HIGH;
bool stableButtonState = HIGH;

unsigned long lastDebounceTime = 0;
const unsigned long debounceDelay = 50;

void hallISR() {
  count++;
}

void setup() {
  Serial.begin(9600);

  pinMode(hallPin, INPUT_PULLUP);
  pinMode(buttonPin, INPUT_PULLUP);
  pinMode(ledPin, OUTPUT);

  attachInterrupt(digitalPinToInterrupt(hallPin), hallISR, FALLING);

  digitalWrite(ledPin, LOW);
}

void loop() {
  bool reading = digitalRead(buttonPin);

  if (reading != lastButtonReading) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (reading != stableButtonState) {
      stableButtonState = reading;

      if (stableButtonState == LOW) {
        loggingState = !loggingState;
        digitalWrite(ledPin, loggingState ? HIGH : LOW);
      }
    }
  }

  lastButtonReading = reading;

  static unsigned long lastSendTime = 0;
  if (millis() - lastSendTime >= 100) {
    Serial.print("COUNT:");
    Serial.println(count);

    Serial.print("LOG:");
    Serial.println(loggingState ? 1 : 0);

    lastSendTime = millis();
  }
}