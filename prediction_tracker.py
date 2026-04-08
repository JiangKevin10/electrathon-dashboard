import math

RACE_LOG_HEADER = [
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
    "wheel_diameter_meters",
    "imu_heading_deg",
    "imu_yaw_rate_dps",
    "imu_ok",
    "gps_speed_mps",
    "rpm_speed_mps",
    "est_x_m",
    "est_y_m",
    "est_source",
]

ROUTE_MODE_GPS = "gps"
ROUTE_MODE_GPS_REPLAY = "gps_replay"
ROUTE_MODE_RPM_IMU = "rpm_imu"
ROUTE_MODE_BLEND = "blend"
ROUTE_MODE_ORDER = [
    ROUTE_MODE_GPS,
    ROUTE_MODE_GPS_REPLAY,
    ROUTE_MODE_RPM_IMU,
    ROUTE_MODE_BLEND,
]

ROUTE_MODE_LABELS = {
    ROUTE_MODE_GPS: "Mode 1: Raw GPS",
    ROUTE_MODE_GPS_REPLAY: "Mode 2: GPS Replay",
    ROUTE_MODE_RPM_IMU: "Mode 3: RPM + IMU",
    ROUTE_MODE_BLEND: "Mode 4: Blended",
}

EARTH_RADIUS_METERS = 6371000.0


def _parse_float(value, default=None):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default


def _parse_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default


def _parse_bool(value):
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y"}


def normalize_angle_degrees(value):
    if value is None:
        return None

    angle = float(value) % 360.0
    if angle < 0:
        angle += 360.0
    return angle


def latlon_to_local_meters(latitude, longitude, anchor_latitude, anchor_longitude):
    latitude_rad = math.radians(latitude)
    anchor_latitude_rad = math.radians(anchor_latitude)
    delta_latitude_rad = math.radians(latitude - anchor_latitude)
    delta_longitude_rad = math.radians(longitude - anchor_longitude)
    mean_latitude_cos = math.cos((latitude_rad + anchor_latitude_rad) / 2.0)
    x_meters = EARTH_RADIUS_METERS * delta_longitude_rad * mean_latitude_cos
    y_meters = EARTH_RADIUS_METERS * delta_latitude_rad
    return x_meters, y_meters


def local_meters_to_latlon(x_meters, y_meters, anchor_latitude, anchor_longitude):
    anchor_latitude_rad = math.radians(anchor_latitude)
    latitude = anchor_latitude + math.degrees(y_meters / EARTH_RADIUS_METERS)
    longitude_scale = math.cos(anchor_latitude_rad)
    if abs(longitude_scale) < 1e-9:
        longitude = anchor_longitude
    else:
        longitude = anchor_longitude + math.degrees(
            x_meters / (EARTH_RADIUS_METERS * longitude_scale)
        )
    return latitude, longitude


def _heading_from_vector(x_meters, y_meters):
    if abs(x_meters) < 1e-9 and abs(y_meters) < 1e-9:
        return None
    return normalize_angle_degrees(math.degrees(math.atan2(x_meters, y_meters)))


def _speed_from_rpm(rpm, wheel_diameter_meters):
    if rpm is None or wheel_diameter_meters is None or wheel_diameter_meters <= 0:
        return None
    return max(float(rpm), 0.0) * math.pi * wheel_diameter_meters / 60.0


def extract_samples(rows, *, fallback_wheel_diameter_meters=0.0):
    samples = []

    for row in rows:
        latitude = _parse_float(row.get("latitude"))
        longitude = _parse_float(row.get("longitude"))
        gps_fix = _parse_bool(row.get("gps_fix")) if "gps_fix" in row else False
        gps_fix = gps_fix and latitude is not None and longitude is not None

        wheel_diameter_meters = _parse_float(
            row.get("wheel_diameter_meters"), fallback_wheel_diameter_meters
        )
        if wheel_diameter_meters is None or wheel_diameter_meters <= 0:
            wheel_diameter_meters = max(float(fallback_wheel_diameter_meters or 0.0), 0.0)

        imu_heading_deg = _parse_float(row.get("imu_heading_deg"))
        imu_yaw_rate_dps = _parse_float(row.get("imu_yaw_rate_dps"))
        imu_ok = _parse_bool(row.get("imu_ok")) if "imu_ok" in row else imu_heading_deg is not None

        samples.append(
            {
                "timestamp": str(row.get("timestamp", "") or "").strip(),
                "elapsed_seconds": _parse_float(row.get("elapsed_seconds"), 0.0) or 0.0,
                "count": _parse_int(row.get("count"), 0) or 0,
                "rpm": _parse_float(row.get("rpm"), 0.0) or 0.0,
                "lap_count": _parse_int(row.get("lap_count"), 0) or 0,
                "race_id": str(row.get("race_id", "") or "").strip(),
                "source": str(row.get("source", "") or "").strip(),
                "latitude": latitude if gps_fix else None,
                "longitude": longitude if gps_fix else None,
                "gps_fix": gps_fix,
                "gps_satellites": _parse_int(row.get("gps_satellites"), 0) or 0,
                "gps_utc_date": str(row.get("gps_utc_date", "") or "").strip(),
                "gps_utc_time": str(row.get("gps_utc_time", "") or "").strip(),
                "wheel_diameter_meters": wheel_diameter_meters,
                "imu_heading_deg": normalize_angle_degrees(imu_heading_deg) if imu_ok else None,
                "imu_yaw_rate_dps": imu_yaw_rate_dps if imu_ok else None,
                "imu_ok": bool(imu_ok and imu_heading_deg is not None),
            }
        )

    return samples


def _build_anchor(samples):
    for sample in samples:
        if sample["gps_fix"]:
            return {
                "latitude": round(sample["latitude"], 6),
                "longitude": round(sample["longitude"], 6),
            }
    return None


def _augment_samples(
    samples,
    *,
    initial_heading_distance_meters,
    blend_weight,
):
    anchor = _build_anchor(samples)
    augmented = [dict(sample) for sample in samples]
    previous_gps_sample = None
    initial_heading_offset_deg = None

    for sample in augmented:
        sample["gps_x_m"] = None
        sample["gps_y_m"] = None
        sample["gps_speed_mps"] = None
        sample["rpm_speed_mps"] = _speed_from_rpm(
            sample["rpm"], sample["wheel_diameter_meters"]
        )
        sample["dr_x_m"] = None
        sample["dr_y_m"] = None
        sample["blend_x_m"] = None
        sample["blend_y_m"] = None
        sample["est_x_m"] = None
        sample["est_y_m"] = None
        sample["est_source"] = ""
        sample["absolute_heading_deg"] = None

        if anchor is not None and sample["gps_fix"]:
            gps_x_m, gps_y_m = latlon_to_local_meters(
                sample["latitude"],
                sample["longitude"],
                anchor["latitude"],
                anchor["longitude"],
            )
            sample["gps_x_m"] = gps_x_m
            sample["gps_y_m"] = gps_y_m

            if previous_gps_sample is not None:
                delta_time = sample["elapsed_seconds"] - previous_gps_sample["elapsed_seconds"]
                if delta_time > 0:
                    delta_x = gps_x_m - previous_gps_sample["gps_x_m"]
                    delta_y = gps_y_m - previous_gps_sample["gps_y_m"]
                    sample["gps_speed_mps"] = math.hypot(delta_x, delta_y) / delta_time

            if (
                initial_heading_offset_deg is None
                and sample["imu_ok"]
                and sample["imu_heading_deg"] is not None
            ):
                heading_distance_meters = math.hypot(gps_x_m, gps_y_m)
                if heading_distance_meters >= initial_heading_distance_meters:
                    initial_heading_offset_deg = normalize_angle_degrees(
                        _heading_from_vector(gps_x_m, gps_y_m) - sample["imu_heading_deg"]
                    )

            previous_gps_sample = sample

    if anchor is None:
        return anchor, augmented, initial_heading_offset_deg

    dr_x_m = 0.0
    dr_y_m = 0.0
    blend_x_m = 0.0
    blend_y_m = 0.0
    previous_elapsed_seconds = None

    for sample in augmented:
        elapsed_seconds = sample["elapsed_seconds"]
        delta_time = 0.0 if previous_elapsed_seconds is None else elapsed_seconds - previous_elapsed_seconds
        if delta_time < 0:
            delta_time = 0.0

        if initial_heading_offset_deg is not None and sample["imu_ok"] and sample["imu_heading_deg"] is not None:
            absolute_heading_deg = normalize_angle_degrees(
                sample["imu_heading_deg"] + initial_heading_offset_deg
            )
            sample["absolute_heading_deg"] = absolute_heading_deg
        else:
            absolute_heading_deg = None

        rpm_speed_mps = sample["rpm_speed_mps"]
        if (
            delta_time > 0
            and absolute_heading_deg is not None
            and rpm_speed_mps is not None
            and rpm_speed_mps >= 0
        ):
            heading_radians = math.radians(absolute_heading_deg)
            delta_distance_m = rpm_speed_mps * delta_time
            delta_x_m = delta_distance_m * math.sin(heading_radians)
            delta_y_m = delta_distance_m * math.cos(heading_radians)
            dr_x_m += delta_x_m
            dr_y_m += delta_y_m
            blend_x_m += delta_x_m
            blend_y_m += delta_y_m

        if absolute_heading_deg is not None and rpm_speed_mps is not None:
            sample["dr_x_m"] = dr_x_m
            sample["dr_y_m"] = dr_y_m

        gps_x_m = sample["gps_x_m"]
        gps_y_m = sample["gps_y_m"]
        if gps_x_m is not None and gps_y_m is not None:
            if sample["dr_x_m"] is None or sample["dr_y_m"] is None:
                blend_x_m = gps_x_m
                blend_y_m = gps_y_m
                sample["est_source"] = "gps"
            else:
                blend_x_m = ((1.0 - blend_weight) * blend_x_m) + (blend_weight * gps_x_m)
                blend_y_m = ((1.0 - blend_weight) * blend_y_m) + (blend_weight * gps_y_m)
                sample["est_source"] = "blend"
            sample["blend_x_m"] = blend_x_m
            sample["blend_y_m"] = blend_y_m
            sample["est_x_m"] = blend_x_m
            sample["est_y_m"] = blend_y_m
        elif sample["dr_x_m"] is not None and sample["dr_y_m"] is not None:
            blend_x_m = sample["dr_x_m"]
            blend_y_m = sample["dr_y_m"]
            sample["blend_x_m"] = blend_x_m
            sample["blend_y_m"] = blend_y_m
            sample["est_x_m"] = blend_x_m
            sample["est_y_m"] = blend_y_m
            sample["est_source"] = "rpm_imu"

        previous_elapsed_seconds = elapsed_seconds

    return anchor, augmented, initial_heading_offset_deg


def _build_point(sample, latitude, longitude, *, x_meters=None, y_meters=None):
    point = {
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
    }

    if sample.get("elapsed_seconds") is not None:
        point["elapsed_seconds"] = round(float(sample["elapsed_seconds"]), 3)
    if sample.get("rpm") is not None:
        point["rpm"] = round(float(sample["rpm"]), 2)
    if sample.get("count") is not None:
        point["count"] = int(sample["count"])
    if sample.get("timestamp"):
        point["timestamp"] = sample["timestamp"]
    if sample.get("imu_heading_deg") is not None:
        point["imu_heading_deg"] = round(float(sample["imu_heading_deg"]), 2)
    if sample.get("imu_yaw_rate_dps") is not None:
        point["imu_yaw_rate_dps"] = round(float(sample["imu_yaw_rate_dps"]), 2)
    if sample.get("gps_speed_mps") is not None:
        point["gps_speed_mps"] = round(float(sample["gps_speed_mps"]), 3)
    if sample.get("rpm_speed_mps") is not None:
        point["rpm_speed_mps"] = round(float(sample["rpm_speed_mps"]), 3)
    if sample.get("est_x_m") is not None:
        point["est_x_m"] = round(float(sample["est_x_m"]), 3)
    if sample.get("est_y_m") is not None:
        point["est_y_m"] = round(float(sample["est_y_m"]), 3)
    if sample.get("est_source"):
        point["est_source"] = sample["est_source"]
    if sample.get("lap_count") is not None:
        point["lap_count"] = int(sample["lap_count"])
    if x_meters is not None:
        point["x_m"] = round(float(x_meters), 3)
    if y_meters is not None:
        point["y_m"] = round(float(y_meters), 3)

    return point


def _route_points_from_gps(samples):
    points = []
    for sample in samples:
        if not sample["gps_fix"]:
            continue
        points.append(
            _build_point(
                sample,
                sample["latitude"],
                sample["longitude"],
                x_meters=sample["gps_x_m"],
                y_meters=sample["gps_y_m"],
            )
        )
    return points


def _route_points_from_local(samples, anchor, x_key, y_key):
    points = []
    if anchor is None:
        return points

    for sample in samples:
        x_meters = sample.get(x_key)
        y_meters = sample.get(y_key)
        if x_meters is None or y_meters is None:
            continue
        latitude, longitude = local_meters_to_latlon(
            x_meters,
            y_meters,
            anchor["latitude"],
            anchor["longitude"],
        )
        points.append(
            _build_point(
                sample,
                latitude,
                longitude,
                x_meters=x_meters,
                y_meters=y_meters,
            )
        )
    return points


def _mode_payload(
    label,
    route_points,
    *,
    session_active,
    start_zone,
    anchor,
    overlay_routes=None,
    current_position=None,
    available=True,
    unavailable_reason=None,
):
    return {
        "label": label,
        "available": bool(available),
        "unavailable_reason": unavailable_reason,
        "session_active": session_active,
        "start_zone": start_zone,
        "anchor_position": anchor,
        "current_position": current_position,
        "route_points": route_points,
        "overlay_routes": overlay_routes or [],
    }


def build_route_modes(
    rows,
    *,
    session_active=False,
    start_zone=None,
    current_position=None,
    fallback_wheel_diameter_meters=0.0,
    blend_weight=0.5,
    initial_heading_distance_meters=2.0,
):
    samples = extract_samples(
        rows, fallback_wheel_diameter_meters=fallback_wheel_diameter_meters
    )
    anchor, augmented_samples, initial_heading_offset_deg = _augment_samples(
        samples,
        initial_heading_distance_meters=initial_heading_distance_meters,
        blend_weight=blend_weight,
    )

    gps_points = _route_points_from_gps(augmented_samples)
    gps_replay_points = _route_points_from_local(augmented_samples, anchor, "gps_x_m", "gps_y_m")
    rpm_imu_points = _route_points_from_local(augmented_samples, anchor, "dr_x_m", "dr_y_m")
    blend_points = _route_points_from_local(augmented_samples, anchor, "blend_x_m", "blend_y_m")

    rpm_mode_reason = None
    if anchor is None:
        rpm_mode_reason = "Need an initial GPS anchor point."
    elif initial_heading_offset_deg is None:
        rpm_mode_reason = "Need IMU data plus early GPS movement to seed the starting direction."
    elif not any(sample["rpm_speed_mps"] is not None for sample in augmented_samples):
        rpm_mode_reason = "Set a wheel diameter before using RPM-based replay."

    gps_current_position = current_position or (gps_points[-1] if gps_points else None)
    gps_replay_current_position = gps_replay_points[-1] if gps_replay_points else gps_current_position
    rpm_current_position = rpm_imu_points[-1] if rpm_imu_points else None
    blend_current_position = blend_points[-1] if blend_points else rpm_current_position or gps_current_position

    modes = {
        ROUTE_MODE_GPS: _mode_payload(
            ROUTE_MODE_LABELS[ROUTE_MODE_GPS],
            gps_points,
            session_active=session_active,
            start_zone=start_zone,
            anchor=anchor,
            current_position=gps_current_position,
            available=bool(gps_points) or current_position is not None,
            unavailable_reason="No GPS fixes are available yet.",
        ),
        ROUTE_MODE_GPS_REPLAY: _mode_payload(
            ROUTE_MODE_LABELS[ROUTE_MODE_GPS_REPLAY],
            gps_replay_points,
            session_active=session_active,
            start_zone=start_zone,
            anchor=anchor,
            current_position=gps_replay_current_position,
            available=bool(gps_replay_points),
            unavailable_reason="Need GPS fixes before the replay route can be built.",
        ),
        ROUTE_MODE_RPM_IMU: _mode_payload(
            ROUTE_MODE_LABELS[ROUTE_MODE_RPM_IMU],
            rpm_imu_points,
            session_active=session_active,
            start_zone=start_zone,
            anchor=anchor,
            current_position=rpm_current_position,
            available=not rpm_mode_reason and bool(rpm_imu_points),
            unavailable_reason=rpm_mode_reason or "No RPM + IMU replay points are available yet.",
            overlay_routes=[
                {
                    "key": "raw_gps",
                    "label": "Raw GPS",
                    "color": "#6b7788",
                    "weight": 4,
                    "opacity": 0.55,
                    "dash_array": "8 10",
                    "points": gps_points,
                }
            ],
        ),
        ROUTE_MODE_BLEND: _mode_payload(
            ROUTE_MODE_LABELS[ROUTE_MODE_BLEND],
            blend_points,
            session_active=session_active,
            start_zone=start_zone,
            anchor=anchor,
            current_position=blend_current_position,
            available=not rpm_mode_reason and bool(blend_points),
            unavailable_reason=rpm_mode_reason or "No blended replay points are available yet.",
            overlay_routes=[
                {
                    "key": "raw_gps",
                    "label": "Raw GPS",
                    "color": "#6b7788",
                    "weight": 4,
                    "opacity": 0.55,
                    "dash_array": "8 10",
                    "points": gps_points,
                },
                {
                    "key": "rpm_imu",
                    "label": "RPM + IMU",
                    "color": "#ef6c00",
                    "weight": 4,
                    "opacity": 0.7,
                    "dash_array": "6 8",
                    "points": rpm_imu_points,
                },
            ],
        ),
    }

    default_mode = ROUTE_MODE_GPS
    for mode_key in [ROUTE_MODE_BLEND, ROUTE_MODE_RPM_IMU, ROUTE_MODE_GPS_REPLAY, ROUTE_MODE_GPS]:
        mode = modes.get(mode_key)
        if mode and mode["available"]:
            default_mode = mode_key
            break

    return {
        "default_mode": default_mode,
        "mode_options": [
            {
                "key": mode_key,
                "label": ROUTE_MODE_LABELS[mode_key],
                "available": modes[mode_key]["available"],
                "unavailable_reason": modes[mode_key]["unavailable_reason"],
            }
            for mode_key in ROUTE_MODE_ORDER
        ],
        "modes": modes,
        "anchor_position": anchor,
        "samples": augmented_samples,
    }


def build_log_rows(
    rows,
    *,
    fallback_wheel_diameter_meters=0.0,
    blend_weight=0.5,
    initial_heading_distance_meters=2.0,
):
    route_data = build_route_modes(
        rows,
        fallback_wheel_diameter_meters=fallback_wheel_diameter_meters,
        blend_weight=blend_weight,
        initial_heading_distance_meters=initial_heading_distance_meters,
    )

    output_rows = []
    for sample in route_data["samples"]:
        output_rows.append(
            [
                sample["timestamp"],
                f"{sample['elapsed_seconds']:.2f}",
                sample["count"],
                round(sample["rpm"], 2),
                sample["lap_count"],
                sample["race_id"],
                sample["source"],
                f"{sample['latitude']:.6f}" if sample["latitude"] is not None else "",
                f"{sample['longitude']:.6f}" if sample["longitude"] is not None else "",
                1 if sample["gps_fix"] else 0,
                sample["gps_satellites"],
                sample["gps_utc_date"],
                sample["gps_utc_time"],
                f"{sample['wheel_diameter_meters']:.4f}"
                if sample["wheel_diameter_meters"] > 0
                else "",
                f"{sample['imu_heading_deg']:.2f}" if sample["imu_heading_deg"] is not None else "",
                f"{sample['imu_yaw_rate_dps']:.2f}"
                if sample["imu_yaw_rate_dps"] is not None
                else "",
                1 if sample["imu_ok"] else 0,
                f"{sample['gps_speed_mps']:.3f}" if sample["gps_speed_mps"] is not None else "",
                f"{sample['rpm_speed_mps']:.3f}" if sample["rpm_speed_mps"] is not None else "",
                f"{sample['est_x_m']:.3f}" if sample["est_x_m"] is not None else "",
                f"{sample['est_y_m']:.3f}" if sample["est_y_m"] is not None else "",
                sample["est_source"],
            ]
        )

    return route_data, output_rows
