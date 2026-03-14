import serial

PORT = "/dev/ttyACM0"
BAUD = 9600

ser = serial.Serial(PORT, BAUD, timeout=1)

print("Reading from Arduino...\n")

while True:
    try:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line:
            print(line)
    except KeyboardInterrupt:
        print("\nStopped.")
        break