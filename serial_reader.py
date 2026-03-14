import serial
import time

PORT = "/dev/ttyACM0"
BAUD = 9600

print("Opening serial...")
ser = serial.Serial(PORT, BAUD, timeout=1)
time.sleep(2)

print("Listening... Press Ctrl+C to stop.")

try:
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line:
            print(line)
        time.sleep(0.01)
except KeyboardInterrupt:
    print("\nStopped.")
finally:
    ser.close()