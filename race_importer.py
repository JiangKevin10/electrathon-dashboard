import csv
from collections import deque
from datetime import datetime, timedelta
from types import SimpleNamespace

from config import LOG_FOLDER, MAGNETS_PER_REV, RAW_LOG_FOLDER
from lap_tracker import (
    DEFAULT_MINIMUM_LAP_SECONDS,
    DEFAULT_START_ZONE_RADIUS_METERS,
    configure_start_zone,
    update_lap_tracking,
)

IMPORTED_RACE_HEADER = [
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
RPM_MEASUREMENT_WINDOW_SECONDS = 2.0


def archive_and_import_raw_race(
    race_id,
    raw_lines,
    start_zone=None,
    radius_meters=DEFAULT_START_ZONE_RADIUS_METERS,
    minimum_lap_seconds=DEFAULT_MINIMUM_LAP_SECONDS,
):
    raw_path, raw_created = archive_raw_race(race_id, raw_lines)
    final_path, import_status = import_raw_race(
        race_id,
        raw_path,
        start_zone=start_zone,
        radius_meters=radius_meters,
        minimum_lap_seconds=minimum_lap_seconds,
    )
    return {
        "raw_path": raw_path,
        "raw_created": raw_created,
        "final_path": final_path,
        "import_status": import_status,
    }


def archive_raw_race(race_id, raw_lines):
    RAW_LOG_FOLDER.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_LOG_FOLDER / f"{_race_slug(race_id)}.csv"

    if raw_path.exists():
        return raw_path, False

    with raw_path.open("w", newline="", encoding="utf-8") as file:
        for line in raw_lines:
            file.write(line.rstrip("\r\n"))
            file.write("\n")

    return raw_path, True


def import_raw_race(
    race_id,
    raw_path,
    start_zone=None,
    radius_meters=DEFAULT_START_ZONE_RADIUS_METERS,
    minimum_lap_seconds=DEFAULT_MINIMUM_LAP_SECONDS,
):
    existing_path = find_existing_race_file(race_id)
    if existing_path is not None:
        return existing_path, "existing"

    with raw_path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        raw_rows = list(reader)

    if not raw_rows:
        raise ValueError(f"Raw race {race_id} is empty.")

    if "elapsed_ms" not in raw_rows[0] or "count" not in raw_rows[0]:
        raise ValueError(f"Raw race {race_id} is missing required columns.")

    race_start_timestamp = _estimate_race_start_datetime(raw_rows)
    final_rows = _build_imported_rows(
        race_id,
        raw_rows,
        start_zone=start_zone,
        radius_meters=radius_meters,
        minimum_lap_seconds=minimum_lap_seconds,
        race_start_timestamp=race_start_timestamp,
    )
    if not final_rows:
        raise ValueError(f"Raw race {race_id} did not contain any valid samples.")

    LOG_FOLDER.mkdir(parents=True, exist_ok=True)
    final_path = _build_final_race_path(race_id, race_start_timestamp)
    with final_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(IMPORTED_RACE_HEADER)
        writer.writerows(final_rows)

    return final_path, "imported"


def find_existing_race_file(race_id):
    LOG_FOLDER.mkdir(parents=True, exist_ok=True)
    race_slug = _race_slug(race_id)

    for path in LOG_FOLDER.glob(f"*_{race_slug}.csv"):
        if path.is_file():
            return path

    for path in LOG_FOLDER.glob("*.csv"):
        if not path.is_file():
            continue

        try:
            with path.open("r", newline="", encoding="utf-8") as file:
                reader = csv.DictReader(file)
                if not reader.fieldnames or "race_id" not in reader.fieldnames:
                    continue

                for row in reader:
                    if str(row.get("race_id", "")).strip() == race_id:
                        return path
        except OSError:
            continue

    return None


def _build_imported_rows(
    race_id,
    raw_rows,
    start_zone,
    radius_meters,
    minimum_lap_seconds,
    race_start_timestamp,
):
    zone = _resolve_start_zone(raw_rows, start_zone, radius_meters, minimum_lap_seconds)
    first_valid_point = _find_first_valid_point(raw_rows)
    lap_state = _build_lap_state(zone, first_valid_point)
    rpm_samples = deque()
    final_rows = []

    for raw_row in raw_rows:
        elapsed_ms = _parse_float(raw_row.get("elapsed_ms"))
        count = _parse_int(raw_row.get("count"))
        if elapsed_ms is None or count is None:
            continue

        elapsed_seconds = max(elapsed_ms / 1000.0, 0.0)
        latitude = _parse_float(raw_row.get("latitude"))
        longitude = _parse_float(raw_row.get("longitude"))
        gps_fix = _parse_bool(raw_row.get("gps_fix"))
        gps_has_fix = gps_fix and latitude is not None and longitude is not None
        gps_satellites = _parse_int(raw_row.get("gps_satellites"), default=0)
        gps_utc_date = str(raw_row.get("gps_utc_date", "") or "").strip()
        gps_utc_time = str(raw_row.get("gps_utc_time", "") or "").strip()

        if rpm_samples and count < rpm_samples[-1][1]:
            rpm_samples.clear()

        rpm_samples.append((elapsed_seconds, count))
        while len(rpm_samples) > 1 and elapsed_seconds - rpm_samples[0][0] > RPM_MEASUREMENT_WINDOW_SECONDS:
            rpm_samples.popleft()

        oldest_elapsed_seconds, oldest_count = rpm_samples[0]
        delta_time = elapsed_seconds - oldest_elapsed_seconds
        delta_count = count - oldest_count
        rpm = 0.0
        if delta_time > 0 and delta_count >= 0:
            rpm = ((delta_count / MAGNETS_PER_REV) / delta_time) * 60.0

        lap_count = 0
        if lap_state is not None:
            lap_state.gps_has_fix = gps_has_fix
            lap_state.gps_latitude = latitude if gps_has_fix else None
            lap_state.gps_longitude = longitude if gps_has_fix else None
            lap_state.session_elapsed_seconds = elapsed_seconds
            update_lap_tracking(lap_state, elapsed_seconds)
            lap_count = lap_state.lap_count

        timestamp = race_start_timestamp + timedelta(seconds=elapsed_seconds)
        final_rows.append(
            [
                timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                f"{elapsed_seconds:.2f}",
                count,
                round(rpm, 2),
                lap_count,
                race_id,
                "arduino_sd",
                f"{latitude:.6f}" if latitude is not None else "",
                f"{longitude:.6f}" if longitude is not None else "",
                1 if gps_has_fix else 0,
                gps_satellites,
                gps_utc_date,
                gps_utc_time,
            ]
        )

    return final_rows


def _estimate_race_start_datetime(raw_rows):
    for row in raw_rows:
        elapsed_ms = _parse_float(row.get("elapsed_ms"))
        gps_datetime = _parse_gps_datetime(row.get("gps_utc_date"), row.get("gps_utc_time"))
        if elapsed_ms is None or gps_datetime is None:
            continue

        return gps_datetime - timedelta(milliseconds=elapsed_ms)

    return datetime.now()


def _resolve_start_zone(raw_rows, configured_zone, radius_meters, minimum_lap_seconds):
    if configured_zone is not None:
        return {
            "latitude": round(float(configured_zone["latitude"]), 6),
            "longitude": round(float(configured_zone["longitude"]), 6),
            "radius_meters": max(float(configured_zone["radius_meters"]), 1.0),
            "minimum_lap_seconds": max(float(configured_zone["minimum_lap_seconds"]), 1.0),
        }

    first_valid_point = _find_first_valid_point(raw_rows)
    if first_valid_point is None:
        return None

    return {
        "latitude": first_valid_point["latitude"],
        "longitude": first_valid_point["longitude"],
        "radius_meters": max(float(radius_meters), 1.0),
        "minimum_lap_seconds": max(float(minimum_lap_seconds), 1.0),
    }


def _find_first_valid_point(raw_rows):
    for row in raw_rows:
        if not _parse_bool(row.get("gps_fix")):
            continue

        latitude = _parse_float(row.get("latitude"))
        longitude = _parse_float(row.get("longitude"))
        if latitude is None or longitude is None:
            continue

        return {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
        }

    return None


def _build_lap_state(zone, first_valid_point):
    if zone is None:
        return None

    state = SimpleNamespace(
        gps_has_fix=first_valid_point is not None,
        gps_latitude=first_valid_point["latitude"] if first_valid_point else None,
        gps_longitude=first_valid_point["longitude"] if first_valid_point else None,
        session_active=True,
        session_started_monotonic=0.0,
        session_elapsed_seconds=0.0,
        start_zone_latitude=None,
        start_zone_longitude=None,
        start_zone_radius_meters=zone["radius_meters"],
        minimum_lap_seconds=zone["minimum_lap_seconds"],
        start_zone_inside=False,
        start_zone_departed=False,
        start_zone_anchor_monotonic=0.0,
        lap_count=0,
        last_lap_elapsed_seconds=None,
    )
    configure_start_zone(
        state,
        zone["latitude"],
        zone["longitude"],
        zone["radius_meters"],
        zone["minimum_lap_seconds"],
        now_monotonic=0.0,
    )
    return state


def _build_final_race_path(race_id, race_start_timestamp):
    timestamp_text = race_start_timestamp.strftime("%Y-%m-%d_%H-%M-%S")
    base_name = f"race_{timestamp_text}_{_race_slug(race_id)}"
    candidate = LOG_FOLDER / f"{base_name}.csv"
    suffix = 1

    while candidate.exists():
        candidate = LOG_FOLDER / f"{base_name}_{suffix}.csv"
        suffix += 1

    return candidate


def _parse_gps_datetime(date_text, time_text):
    date_text = str(date_text or "").strip()
    time_text = str(time_text or "").strip()
    if not date_text or not time_text:
        return None

    try:
        return datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _race_slug(race_id):
    race_id_text = str(race_id or "").strip()
    if race_id_text.lower().endswith(".csv"):
        return race_id_text[:-4]
    return race_id_text or "unknown_race"


def _parse_bool(value):
    value_text = str(value or "").strip().lower()
    return value_text in {"1", "true", "yes", "y"}


def _parse_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None


def _parse_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default
