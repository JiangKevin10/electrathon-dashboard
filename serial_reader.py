import serial
import time

PORT = "/dev/ttyACM0"
BAUD = 9600

ser = serial.Serial(PORT, BAUD, timeout=1)
time.sleep(2)

last_count = 0

print("Listening for counts...")

try:
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()

        if not line:
            continue

        print("RAW:", line)

        if line.startswith("COUNT:"):
            count = int(line.split(":")[1].strip())

            if count != last_count:
                print("Parsed count =", count)
                last_count = count

except KeyboardInterrupt:
    print("\nStopped.")
finally:
    ser.close()