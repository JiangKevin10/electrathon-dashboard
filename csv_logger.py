import csv
from datetime import datetime
from config import LOG_FOLDER
from prediction_tracker import RACE_LOG_HEADER

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
    csv_writer.writerow(RACE_LOG_HEADER)

    state.session_active = True
    state.session_started_at = started_at
    state.session_started_monotonic = started_monotonic
    state.session_elapsed_seconds = 0.0
    state.current_session_filename = str(filename)
    state.current_session_name = filename.name
    state.live_route_points = []
    state.live_samples = []

    print(f"Race session started -> {filename}")


def write_session_row(row_values):
    global csv_file, csv_writer

    if not csv_writer:
        return

    csv_writer.writerow(row_values)
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
