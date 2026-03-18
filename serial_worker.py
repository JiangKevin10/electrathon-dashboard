import serial
import time
from config import PORT, BAUD, MAGNETS_PER_REV
from csv_logger import start_csv, write_row, stop_csv

def run_serial_worker(state):
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
        time.sleep(2)
        ser.reset_input_buffer()
        state.status = f"Connected to {PORT}"
        print(state.status)
    except Exception as e:
        state.status = f"Serial error: {e}"
        print(state.status)
        return

    last_rpm_count = 0
    last_rpm_time = time.time()
    last_logging_on = False

    try:
        while True:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            now = time.time()

            if line:
                print("RAW:", line)

            if line.startswith("COUNT:"):
                try:
                    state.count = int(line.split(":")[1])
                except ValueError:
                    pass

            elif line.startswith("LOG:"):
                try:
                    state.logging_on = (int(line.split(":")[1]) == 1)
                except ValueError:
                    pass

            if state.logging_on and not last_logging_on:
                start_csv(state)

            if not state.logging_on and last_logging_on:
                stop_csv()

            if now - last_rpm_time >= 1.0:
                delta_count = state.count - last_rpm_count
                delta_time = now - last_rpm_time

                if delta_time > 0:
                    state.rpm = ((delta_count / MAGNETS_PER_REV) / delta_time) * 60.0
                else:
                    state.rpm = 0.0

                print(
                    f"COUNT={state.count} RPM={state.rpm:.2f} "
                    f"LOGGING={'ON' if state.logging_on else 'OFF'}"
                )

                if state.logging_on:
                    write_row(state)

                last_rpm_count = state.count
                last_rpm_time = now

            last_logging_on = state.logging_on
            time.sleep(0.01)

    finally:
        stop_csv()
        ser.close()