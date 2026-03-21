from collections import deque

import serial
import time
from config import PORT, BAUD, MAGNETS_PER_REV
from csv_logger import start_session_log, write_session_row, stop_session_log
from lap_tracker import reset_lap_tracking, update_lap_tracking

RPM_UPDATE_INTERVAL = 0.25
RPM_MEASUREMENT_WINDOW = 2.0
LOG_WRITE_INTERVAL = 1.0


def _append_live_route_point(state):
    if not state.session_active:
        return

    if not state.gps_has_fix or state.gps_latitude is None or state.gps_longitude is None:
        return

    point = {
        "latitude": round(state.gps_latitude, 6),
        "longitude": round(state.gps_longitude, 6),
    }
    if state.live_route_points and state.live_route_points[-1] == point:
        return

    state.live_route_points.append(point)


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

            elif line.startswith("GPS:"):
                print(f"[ARDUINO] {line}")
                state.last_raw_gps_line = line
                gps_payload = line.split(":", 1)[1].strip()
                if gps_payload == "NOFIX":
                    state.gps_latitude = None
                    state.gps_longitude = None
                    state.gps_has_fix = False
                    state.gps_satellites = 0
                else:
                    gps_parts = gps_payload.split(",")
                    if len(gps_parts) >= 3:
                        try:
                            state.gps_latitude = float(gps_parts[0])
                            state.gps_longitude = float(gps_parts[1])
                            state.gps_satellites = int(gps_parts[2])
                            state.gps_has_fix = True
                            if state.session_active and state.session_started_monotonic is not None:
                                state.session_elapsed_seconds = now - state.session_started_monotonic
                            update_lap_tracking(state, now)
                            _append_live_route_point(state)
                        except ValueError:
                            pass

            elif line.startswith("GPSTIME:"):
                print(f"[ARDUINO] {line}")
                state.last_raw_gpstime_line = line
                time_payload = line.split(":", 1)[1].strip()
                if time_payload == "NOFIX":
                    state.gps_utc_date = None
                    state.gps_utc_time = None
                else:
                    time_parts = time_payload.split(",")
                    if len(time_parts) >= 2:
                        state.gps_utc_date = time_parts[0]
                        state.gps_utc_time = time_parts[1]

            if state.count < rpm_samples[-1][1]:
                rpm_samples.clear()
                rpm_samples.append((now, state.count))
                state.rpm = 0.0

            if state.session_requested and not last_session_requested:
                start_session_log(state, now)
                reset_lap_tracking(state, anchor_monotonic=now)
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
        state.gps_latitude = None
        state.gps_longitude = None
        state.gps_has_fix = False
        state.gps_satellites = 0
        state.gps_utc_date = None
        state.gps_utc_time = None
        state.last_raw_gps_line = "Waiting for GPS serial data"
        state.last_raw_gpstime_line = "Waiting for GPS time data"
        state.live_route_points = []
        reset_lap_tracking(state)
        stop_session_log(state)
        ser.close()
