from collections import deque

import serial
import time
from config import PORT, BAUD, MAGNETS_PER_REV
from csv_logger import start_session_log, write_session_row, stop_session_log
from lap_tracker import has_start_zone, reset_lap_tracking, update_lap_tracking
from race_importer import archive_and_import_raw_race

RPM_UPDATE_INTERVAL = 0.25
RPM_MEASUREMENT_WINDOW = 2.0
LOG_WRITE_INTERVAL = 1.0
SYNC_LIST_TIMEOUT_SECONDS = 4.0
SYNC_FILE_TIMEOUT_SECONDS = 10.0
SYNC_ACK_TIMEOUT_SECONDS = 4.0


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


def _handle_live_serial_line(state, line, now):
    if line.startswith("COUNT:"):
        try:
            state.count = int(line.split(":", 1)[1])
        except ValueError:
            pass
        return True

    if line.startswith("LOG:"):
        try:
            state.session_requested = (int(line.split(":", 1)[1]) == 1)
        except ValueError:
            pass
        return True

    if line.startswith("RACEFILE:"):
        race_id = line.split(":", 1)[1].strip()
        state.current_race_id = race_id or None
        return True

    if line.startswith("GPS:"):
        print(f"[ARDUINO] {line}")
        state.last_raw_gps_line = line
        gps_payload = line.split(":", 1)[1].strip()
        if gps_payload == "NOFIX":
            state.gps_latitude = None
            state.gps_longitude = None
            state.gps_has_fix = False
            state.gps_satellites = 0
            return True

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
        return True

    if line.startswith("GPSTIME:"):
        print(f"[ARDUINO] {line}")
        state.last_raw_gpstime_line = line
        time_payload = line.split(":", 1)[1].strip()
        if time_payload == "NOFIX":
            state.gps_utc_date = None
            state.gps_utc_time = None
            return True

        time_parts = time_payload.split(",")
        if len(time_parts) >= 2:
            state.gps_utc_date = time_parts[0]
            state.gps_utc_time = time_parts[1]
        return True

    return False


def _send_command(ser, command_text):
    ser.write(f"{command_text}\n".encode("utf-8"))
    ser.flush()


def _read_protocol_line(ser, state, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        now = time.monotonic()
        if not line:
            continue

        if _handle_live_serial_line(state, line, now):
            continue

        return line

    raise TimeoutError("Timed out waiting for the Arduino response.")


def _current_start_zone_config(state):
    if not has_start_zone(state):
        return None

    return {
        "latitude": state.start_zone_latitude,
        "longitude": state.start_zone_longitude,
        "radius_meters": state.start_zone_radius_meters,
        "minimum_lap_seconds": state.minimum_lap_seconds,
    }


def _request_stored_races(ser, state):
    ser.reset_input_buffer()
    _send_command(ser, "CMD:LIST")
    races = []
    list_started = False

    while True:
        line = _read_protocol_line(ser, state, SYNC_LIST_TIMEOUT_SECONDS)

        if line == "LIST:BEGIN":
            list_started = True
            continue

        if line == "LIST:END":
            if not list_started:
                raise RuntimeError("Arduino ended the race list before starting it.")
            return races

        if line.startswith("LIST:ITEM:"):
            payload = line.split(":", 2)[2]
            race_id = payload.split(",", 1)[0].strip()
            if race_id:
                races.append(race_id)
            continue

        if line.startswith("ERROR:"):
            raise RuntimeError(line.split(":", 1)[1].strip() or "Arduino list command failed.")


def _receive_race_file(ser, state, race_id):
    ser.reset_input_buffer()
    _send_command(ser, f"CMD:SEND:{race_id}")
    raw_lines = []
    file_started = False

    while True:
        line = _read_protocol_line(ser, state, SYNC_FILE_TIMEOUT_SECONDS)

        if line.startswith("FILE:BEGIN:"):
            payload = line.split(":", 2)[2]
            if not payload.startswith(race_id):
                raise RuntimeError(f"Arduino started sending the wrong race: {payload}")
            file_started = True
            continue

        if line.startswith("FILE:DATA:"):
            raw_lines.append(line.split(":", 2)[2])
            continue

        if line == f"FILE:END:{race_id}":
            if not file_started:
                raise RuntimeError(f"Arduino ended race {race_id} before it started sending data.")
            return raw_lines

        if line.startswith("ERROR:"):
            raise RuntimeError(line.split(":", 1)[1].strip() or f"Arduino could not send {race_id}.")


def _acknowledge_race(ser, state, race_id):
    ser.reset_input_buffer()
    _send_command(ser, f"ACK:{race_id}")

    while True:
        line = _read_protocol_line(ser, state, SYNC_ACK_TIMEOUT_SECONDS)
        if line == f"ACK:OK:{race_id}":
            return

        if line.startswith("ERROR:"):
            raise RuntimeError(line.split(":", 1)[1].strip() or f"Arduino failed to ACK {race_id}.")


def _delete_race_on_arduino(ser, state, race_id):
    ser.reset_input_buffer()
    _send_command(ser, f"CMD:DELETE:{race_id}")

    while True:
        line = _read_protocol_line(ser, state, SYNC_ACK_TIMEOUT_SECONDS)
        if line == f"DELETE:OK:{race_id}":
            return

        if line.startswith("ERROR:"):
            raise RuntimeError(line.split(":", 1)[1].strip() or f"Arduino failed to delete {race_id}.")


def _sync_stored_races(ser, state):
    state.sync_requested = False

    if state.session_requested or state.session_active:
        state.sync_status_text = "Sync was skipped because a race is still running."
        return

    state.sync_in_progress = True
    imported_count = 0
    existing_count = 0
    failed_races = []

    try:
        state.sync_status_text = "Checking the Arduino SD card for stored races..."
        stored_races = _request_stored_races(ser, state)
        if not stored_races:
            state.sync_status_text = "Sync complete. No stored races were waiting on the Arduino."
            return

        zone_config = _current_start_zone_config(state)
        for index, race_id in enumerate(stored_races, start=1):
            state.sync_status_text = f"Syncing {race_id} ({index}/{len(stored_races)})..."
            try:
                raw_lines = _receive_race_file(ser, state, race_id)
                import_summary = archive_and_import_raw_race(
                    race_id,
                    raw_lines,
                    start_zone=zone_config,
                    radius_meters=state.start_zone_radius_meters,
                    minimum_lap_seconds=state.minimum_lap_seconds,
                )
                _acknowledge_race(ser, state, race_id)

                if import_summary["import_status"] == "imported":
                    imported_count += 1
                    state.last_session_filename = str(import_summary["final_path"])
                    state.last_session_name = import_summary["final_path"].name
                else:
                    existing_count += 1
            except Exception as exc:
                failed_races.append(f"{race_id} ({exc})")

        status_parts = [
            f"Sync complete. Imported {imported_count} race(s).",
            f"{existing_count} already existed on the Pi.",
        ]
        if failed_races:
            preview = "; ".join(failed_races[:2])
            if len(failed_races) > 2:
                preview += f"; and {len(failed_races) - 2} more"
            status_parts.append(f"Failed {len(failed_races)} race(s): {preview}.")

        state.sync_status_text = " ".join(status_parts)
    except Exception as exc:
        state.sync_status_text = f"Sync failed: {exc}"
    finally:
        state.sync_in_progress = False


def _delete_stored_race(ser, state):
    race_id = state.delete_requested_race_id
    state.delete_requested_race_id = None

    if not race_id:
        state.sync_status_text = "Delete request failed because no race ID was provided."
        return

    if state.session_requested or state.session_active:
        state.sync_status_text = "Delete was skipped because a race is still running."
        return

    state.sync_in_progress = True

    try:
        state.sync_status_text = f"Deleting stored race {race_id}..."
        _delete_race_on_arduino(ser, state, race_id)
        state.sync_status_text = f"Deleted stored race {race_id} from the Arduino."
    except Exception as exc:
        state.sync_status_text = f"Delete failed for {race_id}: {exc}"
    finally:
        state.sync_in_progress = False


def run_serial_worker(state):
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
        time.sleep(2)
        ser.reset_input_buffer()
        state.serial_connected = True
        state.status = f"Connected to {PORT}"
        print(state.status)
    except Exception as exc:
        state.serial_connected = False
        state.status = f"Serial error: {exc}"
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

            if line:
                _handle_live_serial_line(state, line, now)

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
                state.current_race_id = None

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

            if state.delete_requested_race_id and not state.sync_in_progress:
                _delete_stored_race(ser, state)
                now = time.monotonic()
                last_rpm_time = now
                last_log_time = now
                rpm_samples.clear()
                rpm_samples.append((now, state.count))

            if state.sync_requested and not state.sync_in_progress:
                _sync_stored_races(ser, state)
                now = time.monotonic()
                last_rpm_time = now
                last_log_time = now
                rpm_samples.clear()
                rpm_samples.append((now, state.count))

            last_session_requested = state.session_requested
            time.sleep(0.01)

    except Exception as exc:
        state.status = f"Serial worker stopped: {exc}"
        print(state.status)
    finally:
        state.serial_connected = False
        state.sync_in_progress = False
        state.delete_requested_race_id = None
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
        state.current_race_id = None
        reset_lap_tracking(state)
        stop_session_log(state)
        ser.close()
