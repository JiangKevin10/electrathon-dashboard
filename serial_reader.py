import serial
import time

ser = serial.Serial("/dev/ttyACM0", 9600, timeout=0.1)
time.sleep(2)

magnets_per_rev = 1

count = 0
last_rpm_count = 0
last_rpm_time = time.time()

print("Listening... Press Ctrl+C to stop.\n")

try:
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        now = time.time()
        clock = time.strftime("%H:%M:%S", time.localtime(now))

        if line and line.startswith("COUNT:"):
            count = int(line.split(":")[1])
            

        if now - last_rpm_time >= 1.0:
            delta_count = count - last_rpm_count
            delta_time = now - last_rpm_time

            if delta_time > 0:
                rpm = ((delta_count / magnets_per_rev) / delta_time) * 60
            else:
                rpm = 0

            print(f"[{clock}] RPM = {rpm:.2f}")

            last_rpm_count = count
            last_rpm_time = now

except KeyboardInterrupt:
    print("\nStopped.")
finally:
    ser.close()