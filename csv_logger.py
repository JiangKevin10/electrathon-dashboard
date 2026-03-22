import csv
from datetime import datetime
from config import LOG_FOLDER

csv_file = None
csv_writer = None


def start_session_log(state, started_monotonic):
    global csv_file, csv_writer

    if csv_file:
        return

    LOG_FOLDER.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now()
    filename = LOG_FOLDER / f"race_{started_at.strftime('%Y-%m-%d_%H-%M-%S')}.csv"

    csv_file = open(filename, "w", newline="", encoding="utf-8")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(
        [
            "timestamp",
            "elapsed_seconds",
            "count",
            "rpm",
            "lap_count",
            "race_id",
            "source",
            "latitude",
            "longitude",
            "gps_fix",
            "gps_satellites",
            "gps_utc_date",
            "gps_utc_time",
        ]
    )

    state.session_active = True
    state.session_started_at = started_at
    state.session_started_monotonic = started_monotonic
    state.session_elapsed_seconds = 0.0
    state.current_session_filename = str(filename)
    state.current_session_name = filename.name
    state.live_route_points = []
    if state.gps_has_fix and state.gps_latitude is not None and state.gps_longitude is not None:
        state.live_route_points.append(
            {
                "latitude": round(state.gps_latitude, 6),
                "longitude": round(state.gps_longitude, 6),
            }
        )

    print(f"Race session started -> {filename}")


def write_session_row(state):
    global csv_file, csv_writer

    if not csv_writer or not state.session_active:
        return

    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    csv_writer.writerow(
        [
            timestamp_str,
            f"{state.session_elapsed_seconds:.2f}",
            state.count,
            round(state.rpm, 2),
            state.lap_count,
            state.current_race_id or "",
            "live_serial",
            f"{state.gps_latitude:.6f}" if state.gps_latitude is not None else "",
            f"{state.gps_longitude:.6f}" if state.gps_longitude is not None else "",
            1 if state.gps_has_fix else 0,
            state.gps_satellites,
            state.gps_utc_date or "",
            state.gps_utc_time or "",
        ]
    )
    csv_file.flush()


def stop_session_log(state):
    global csv_file, csv_writer

    state.session_active = False
    state.session_elapsed_seconds = 0.0
    state.session_started_at = None
    state.session_started_monotonic = None
    if state.current_session_filename:
        state.last_session_filename = state.current_session_filename
        state.last_session_name = state.current_session_name
    state.current_session_filename = None
    state.current_session_name = None

    if csv_file:
        csv_file.close()
        csv_file = None
        csv_writer = None
        print("Race session stopped")
