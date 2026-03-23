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
SYNC_FILE_TIMEOUT_SECONDS = 60.0
SYNC_ACK_TIMEOUT_SECONDS = 4.0
DELETE_ALL_TIMEOUT_SECONDS = 60.0
PROTOCOL_RETRY_ATTEMPTS = 3
PROTOCOL_RETRY_DELAY_SECONDS = 0.35
SYNC_PASS_ATTEMPTS = 3


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


def _is_retryable_protocol_error(exc):
    if isinstance(exc, TimeoutError):
        return True

    message = str(exc or "")
    return "UNKNOWN_COMMAND" in message or "Timed out waiting" in message


def _run_protocol_action(action):
    last_error = None

    for attempt in range(1, PROTOCOL_RETRY_ATTEMPTS + 1):
        try:
            return action()
        except Exception as exc:
            last_error = exc
            if attempt >= PROTOCOL_RETRY_ATTEMPTS or not _is_retryable_protocol_error(exc):
                raise
            time.sleep(PROTOCOL_RETRY_DELAY_SECONDS)

    raise last_error


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


def _reset_sync_progress(state):
    state.sync_total_races = 0
    state.sync_current_race_index = 0
    state.sync_current_race_id = None
    state.sync_bytes_received = 0
    state.sync_total_bytes = 0
    state.sync_eta_seconds = None


def _begin_race_sync_progress(state, race_id, race_index, total_races, total_bytes):
    state.sync_total_races = total_races
    state.sync_current_race_index = race_index
    state.sync_current_race_id = race_id
    state.sync_bytes_received = 0
    state.sync_total_bytes = max(int(total_bytes or 0), 0)
    state.sync_eta_seconds = None


def _update_sync_progress(state, bytes_received, total_bytes, started_monotonic):
    state.sync_bytes_received = max(int(bytes_received or 0), 0)
    if total_bytes is not None:
        state.sync_total_bytes = max(int(total_bytes), 0)

    if started_monotonic is None or state.sync_bytes_received <= 0:
        state.sync_eta_seconds = None
        return

    elapsed_seconds = max(time.monotonic() - started_monotonic, 0.001)
    if state.sync_total_bytes <= 0:
        state.sync_eta_seconds = None
        return

    remaining_bytes = max(state.sync_total_bytes - state.sync_bytes_received, 0)
    transfer_rate = state.sync_bytes_received / elapsed_seconds
    state.sync_eta_seconds = (remaining_bytes / transfer_rate) if transfer_rate > 0 else None


def _format_race_preview(race_items, *, with_details=False):
    if not race_items:
        return None

    preview_limit = 3
    preview_items = race_items[:preview_limit]
    separator = "; " if with_details else ", "
    preview_text = separator.join(preview_items)
    if len(race_items) > preview_limit:
        preview_text += f"{separator}and {len(race_items) - preview_limit} more"
    return preview_text


def _request_stored_races(ser, state):
    def run():
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
                payload_parts = payload.split(",", 1)
                race_id = payload_parts[0].strip()
                size_bytes = None
                if len(payload_parts) > 1:
                    try:
                        size_bytes = int(payload_parts[1].strip())
                    except ValueError:
                        size_bytes = None
                if race_id:
                    races.append(
                        {
                            "race_id": race_id,
                            "size_bytes": size_bytes,
                        }
                    )
                continue

            if line.startswith("ERROR:"):
                raise RuntimeError(line.split(":", 1)[1].strip() or "Arduino list command failed.")

    return _run_protocol_action(run)


def _receive_race_file(ser, state, race_id, expected_size_bytes=None):
    def run():
        ser.reset_input_buffer()
        _send_command(ser, f"CMD:SEND:{race_id}")
        raw_lines = []
        file_started = False
        transfer_started_monotonic = None
        total_bytes = max(int(expected_size_bytes or 0), 0)
        bytes_received = 0

        while True:
            line = _read_protocol_line(ser, state, SYNC_FILE_TIMEOUT_SECONDS)

            if line.startswith("FILE:BEGIN:"):
                payload = line.split(":", 2)[2]
                payload_parts = payload.split(",", 1)
                file_race_id = payload_parts[0].strip()
                if file_race_id != race_id:
                    raise RuntimeError(f"Arduino started sending the wrong race: {payload}")
                if len(payload_parts) > 1:
                    try:
                        total_bytes = int(payload_parts[1].strip())
                    except ValueError:
                        total_bytes = max(int(expected_size_bytes or 0), 0)
                file_started = True
                transfer_started_monotonic = time.monotonic()
                _update_sync_progress(state, 0, total_bytes, transfer_started_monotonic)
                continue

            if line.startswith("FILE:DATA:"):
                raw_line = line.split(":", 2)[2]
                raw_lines.append(raw_line)
                bytes_received += len(raw_line.encode("utf-8")) + 2
                if total_bytes > 0:
                    bytes_received = min(bytes_received, total_bytes)
                _update_sync_progress(state, bytes_received, total_bytes, transfer_started_monotonic)
                continue

            if line == f"FILE:END:{race_id}":
                if not file_started:
                    raise RuntimeError(f"Arduino ended race {race_id} before it started sending data.")
                _update_sync_progress(
                    state,
                    total_bytes if total_bytes > 0 else bytes_received,
                    total_bytes,
                    transfer_started_monotonic,
                )
                return raw_lines

            if line.startswith("ERROR:"):
                raise RuntimeError(line.split(":", 1)[1].strip() or f"Arduino could not send {race_id}.")

    return _run_protocol_action(run)


def _acknowledge_race(ser, state, race_id):
    def run():
        ser.reset_input_buffer()
        _send_command(ser, f"ACK:{race_id}")

        while True:
            line = _read_protocol_line(ser, state, SYNC_ACK_TIMEOUT_SECONDS)
            if line == f"ACK:OK:{race_id}":
                return

            if line.startswith("ERROR:"):
                raise RuntimeError(line.split(":", 1)[1].strip() or f"Arduino failed to ACK {race_id}.")

    return _run_protocol_action(run)


def _delete_race_on_arduino(ser, state, race_id):
    def run():
        ser.reset_input_buffer()
        _send_command(ser, f"CMD:DELETE:{race_id}")

        while True:
            line = _read_protocol_line(ser, state, SYNC_ACK_TIMEOUT_SECONDS)
            if line == f"DELETE:OK:{race_id}":
                return

            if line.startswith("ERROR:"):
                raise RuntimeError(line.split(":", 1)[1].strip() or f"Arduino failed to delete {race_id}.")

    return _run_protocol_action(run)


def _delete_all_races_on_arduino(ser, state):
    def run():
        ser.reset_input_buffer()
        _send_command(ser, "CMD:DELETE_ALL")
        delete_started = False

        while True:
            line = _read_protocol_line(ser, state, DELETE_ALL_TIMEOUT_SECONDS)
            if line == "DELETEALL:BEGIN":
                delete_started = True
                state.sync_status_text = "Deleting all stored races from the Arduino..."
                continue

            if line.startswith("DELETEALL:PROGRESS:"):
                delete_started = True
                try:
                    deleted_count = int(line.split(":", 2)[2].strip())
                except ValueError:
                    deleted_count = None

                if deleted_count is not None:
                    state.sync_status_text = (
                        f"Deleting all stored races from the Arduino... "
                        f"{deleted_count} deleted so far."
                    )
                continue

            if line.startswith("DELETEALL:OK:"):
                try:
                    return int(line.split(":", 2)[2].strip())
                except ValueError:
                    return 0

            if line.startswith("ERROR:"):
                raise RuntimeError(line.split(":", 1)[1].strip() or "Arduino failed to delete all stored races.")

            if delete_started:
                continue

    return _run_protocol_action(run)


def _sync_stored_races(ser, state):
    state.sync_requested = False

    if state.session_requested or state.session_active:
        state.sync_status_text = "Sync was skipped because a race is still running."
        return

    state.sync_in_progress = True
    _reset_sync_progress(state)
    imported_races = []
    existing_races = []
    failed_races = []

    try:
        state.sync_status_text = "Checking the Arduino SD card for stored races..."
        stored_races = _request_stored_races(ser, state)
        if not stored_races:
            state.sync_status_text = "Sync complete. No stored races were waiting on the Arduino."
            return

        zone_config = _current_start_zone_config(state)
        remaining_races = stored_races
        for sync_pass_index in range(1, SYNC_PASS_ATTEMPTS + 1):
            if not remaining_races:
                break

            pass_failures = []
            total_races = len(remaining_races)
            for index, stored_race in enumerate(remaining_races, start=1):
                race_id = stored_race["race_id"]
                _begin_race_sync_progress(
                    state,
                    race_id,
                    index,
                    total_races,
                    stored_race.get("size_bytes") or 0,
                )
                if sync_pass_index == 1:
                    state.sync_status_text = f"Syncing {race_id} ({index}/{total_races})..."
                else:
                    state.sync_status_text = (
                        f"Retrying {race_id} ({index}/{total_races}, pass {sync_pass_index}/{SYNC_PASS_ATTEMPTS})..."
                    )
                try:
                    raw_lines = _receive_race_file(
                        ser,
                        state,
                        race_id,
                        expected_size_bytes=stored_race.get("size_bytes"),
                    )
                    import_summary = archive_and_import_raw_race(
                        race_id,
                        raw_lines,
                        start_zone=zone_config,
                        radius_meters=state.start_zone_radius_meters,
                        minimum_lap_seconds=state.minimum_lap_seconds,
                    )
                    _acknowledge_race(ser, state, race_id)

                    if import_summary["import_status"] == "imported":
                        if race_id not in imported_races:
                            imported_races.append(race_id)
                        state.last_session_filename = str(import_summary["final_path"])
                        state.last_session_name = import_summary["final_path"].name
                    else:
                        if race_id not in existing_races:
                            existing_races.append(race_id)
                except Exception as exc:
                    pass_failures.append(
                        {
                            "race_id": race_id,
                            "error": str(exc),
                        }
                    )

            if not pass_failures:
                failed_races = []
                break

            if sync_pass_index >= SYNC_PASS_ATTEMPTS:
                failed_races = [f"{item['race_id']} ({item['error']})" for item in pass_failures]
                break

            failed_ids = {item["race_id"] for item in pass_failures}
            time.sleep(PROTOCOL_RETRY_DELAY_SECONDS)
            listed_again = _request_stored_races(ser, state)
            remaining_races = [race for race in listed_again if race["race_id"] in failed_ids]
            if not remaining_races:
                failed_races = []
                break

        _reset_sync_progress(state)
        status_prefix = "Sync complete." if not failed_races else "Sync partial."
        status_parts = [f"{status_prefix} Imported {len(imported_races)} race(s)."]
        imported_preview = _format_race_preview(imported_races)
        if imported_preview:
            status_parts.append(f"Imported IDs: {imported_preview}.")

        status_parts.append(f"{len(existing_races)} already existed on the Pi.")
        existing_preview = _format_race_preview(existing_races)
        if existing_preview:
            status_parts.append(f"Existing IDs: {existing_preview}.")

        if failed_races:
            status_parts.append(
                f"Failed {len(failed_races)} race(s): {_format_race_preview(failed_races, with_details=True)}."
            )

        state.sync_status_text = " ".join(status_parts)
    except Exception as exc:
        _reset_sync_progress(state)
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


def _delete_all_stored_races(ser, state):
    state.delete_all_requested = False

    if state.session_requested or state.session_active:
        state.sync_status_text = "Delete all was skipped because a race is still running."
        return

    state.sync_in_progress = True
    _reset_sync_progress(state)

    try:
        state.sync_status_text = "Deleting all stored races from the Arduino..."
        deleted_count = _delete_all_races_on_arduino(ser, state)
        state.sync_status_text = f"Deleted {deleted_count} stored race(s) from the Arduino."
    except Exception as exc:
        state.sync_status_text = f"Delete all failed: {exc}"
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

            if state.delete_all_requested and not state.sync_in_progress:
                _delete_all_stored_races(ser, state)
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
        state.delete_all_requested = False
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
        _reset_sync_progress(state)
        reset_lap_tracking(state)
        stop_session_log(state)
        ser.close()
