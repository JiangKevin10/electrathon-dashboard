import serial
import time
from config import PORT, BAUD, MAGNETS_PER_REV
from csv_logger import start_session_log, write_session_row, stop_session_log

RPM_UPDATE_INTERVAL = 0.25
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

    last_rpm_count = 0
    last_rpm_time = time.monotonic()
    last_log_time = last_rpm_time
    last_session_requested = False

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

            if state.session_requested and not last_session_requested:
                start_session_log(state, now)
                last_rpm_count = state.count
                last_rpm_time = now
                last_log_time = now

            if not state.session_requested and last_session_requested:
                stop_session_log(state)

            if state.session_active and state.session_started_monotonic is not None:
                state.session_elapsed_seconds = now - state.session_started_monotonic

            if now - last_rpm_time >= RPM_UPDATE_INTERVAL:
                delta_count = state.count - last_rpm_count
                delta_time = now - last_rpm_time

                if delta_time > 0 and delta_count >= 0:
                    state.rpm = ((delta_count / MAGNETS_PER_REV) / delta_time) * 60.0
                else:
                    state.rpm = 0.0

                last_rpm_count = state.count
                last_rpm_time = now

            if now - last_log_time >= LOG_WRITE_INTERVAL:

                print(
                    f"COUNT={state.count} RPM={state.rpm:.2f} "
                    f"SESSION={'ON' if state.session_active else 'OFF'}"
                )

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
