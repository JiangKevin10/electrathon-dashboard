from collections import deque

import serial
import time
from config import PORT, BAUD, MAGNETS_PER_REV
from csv_logger import start_session_log, write_session_row, stop_session_log

RPM_UPDATE_INTERVAL = 0.25
RPM_MEASUREMENT_WINDOW = 2.0
LOG_WRITE_INTERVAL = 1.0


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

    last_rpm_time = time.monotonic()
    last_log_time = last_rpm_time
    last_session_requested = False
    rpm_samples = deque([(last_rpm_time, state.count)])

    try:
        while True:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            now = time.monotonic()

            if line.startswith("COUNT:"):
                try:
                    state.count = int(line.split(":")[1])
                except ValueError:
                    pass

            elif line.startswith("LOG:"):
                try:
                    state.session_requested = (int(line.split(":")[1]) == 1)
                except ValueError:
                    pass

            if state.count < rpm_samples[-1][1]:
                rpm_samples.clear()
                rpm_samples.append((now, state.count))
                state.rpm = 0.0

            if state.session_requested and not last_session_requested:
                start_session_log(state, now)
                last_rpm_time = now
                last_log_time = now
                rpm_samples.clear()
                rpm_samples.append((now, state.count))
                state.rpm = 0.0

            if not state.session_requested and last_session_requested:
                stop_session_log(state)

            if state.session_active and state.session_started_monotonic is not None:
                state.session_elapsed_seconds = now - state.session_started_monotonic

            if now - last_rpm_time >= RPM_UPDATE_INTERVAL:
                rpm_samples.append((now, state.count))

                while len(rpm_samples) > 1 and now - rpm_samples[0][0] > RPM_MEASUREMENT_WINDOW:
                    rpm_samples.popleft()

                oldest_time, oldest_count = rpm_samples[0]
                delta_count = state.count - oldest_count
                delta_time = now - oldest_time

                if delta_time > 0 and delta_count >= 0:
                    state.rpm = ((delta_count / MAGNETS_PER_REV) / delta_time) * 60.0
                else:
                    state.rpm = 0.0

                last_rpm_time = now

            if now - last_log_time >= LOG_WRITE_INTERVAL:
                if state.session_active:
                    write_session_row(state)

                last_log_time = now

            last_session_requested = state.session_requested
            time.sleep(0.01)

    except Exception as e:
        state.status = f"Serial worker stopped: {e}"
        print(state.status)
    finally:
        state.session_requested = False
        stop_session_log(state)
        ser.close()
