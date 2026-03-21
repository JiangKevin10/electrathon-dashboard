from math import atan2, cos, radians, sin, sqrt


EARTH_RADIUS_METERS = 6_371_000.0
DEFAULT_START_ZONE_RADIUS_METERS = 12.0
DEFAULT_MINIMUM_LAP_SECONDS = 120.0


def has_start_zone(state):
    return (
        state.start_zone_latitude is not None
        and state.start_zone_longitude is not None
        and state.start_zone_radius_meters > 0
    )


def current_position_inside_start_zone(state):
    if (
        not has_start_zone(state)
        or not state.gps_has_fix
        or state.gps_latitude is None
        or state.gps_longitude is None
    ):
        return False

    return (
        _distance_meters(
            state.gps_latitude,
            state.gps_longitude,
            state.start_zone_latitude,
            state.start_zone_longitude,
        )
        <= state.start_zone_radius_meters
    )


def configure_start_zone(
    state,
    latitude,
    longitude,
    radius_meters,
    minimum_lap_seconds,
    now_monotonic=None,
):
    state.start_zone_latitude = round(float(latitude), 6)
    state.start_zone_longitude = round(float(longitude), 6)
    state.start_zone_radius_meters = max(float(radius_meters), 1.0)
    state.minimum_lap_seconds = max(float(minimum_lap_seconds), 1.0)
    reset_lap_tracking(state, anchor_monotonic=now_monotonic if state.session_active else None)


def clear_start_zone(state):
    state.start_zone_latitude = None
    state.start_zone_longitude = None
    state.start_zone_inside = False
    state.start_zone_departed = False
    state.start_zone_anchor_monotonic = None
    state.lap_count = 0
    state.last_lap_elapsed_seconds = None


def reset_lap_tracking(state, anchor_monotonic=None):
    state.lap_count = 0
    state.last_lap_elapsed_seconds = None
    state.start_zone_anchor_monotonic = anchor_monotonic

    if has_start_zone(state):
        inside_zone = current_position_inside_start_zone(state)
        state.start_zone_inside = inside_zone
        state.start_zone_departed = (
            not inside_zone and state.gps_has_fix and state.gps_latitude is not None and state.gps_longitude is not None
        )
        return

    state.start_zone_inside = False
    state.start_zone_departed = False


def update_lap_tracking(state, now_monotonic):
    if not has_start_zone(state):
        state.start_zone_inside = False
        state.start_zone_departed = False
        return

    inside_zone = current_position_inside_start_zone(state)
    previous_inside_zone = state.start_zone_inside
    state.start_zone_inside = inside_zone

    if not state.session_active or state.session_started_monotonic is None:
        return

    if not inside_zone and not state.start_zone_departed:
        state.start_zone_departed = True

    if inside_zone == previous_inside_zone:
        return

    if not inside_zone:
        state.start_zone_departed = True
        return

    enough_time_elapsed = (
        state.start_zone_anchor_monotonic is not None
        and (now_monotonic - state.start_zone_anchor_monotonic) >= state.minimum_lap_seconds
    )
    if state.start_zone_departed and enough_time_elapsed:
        state.lap_count += 1
        state.last_lap_elapsed_seconds = state.session_elapsed_seconds
        state.start_zone_anchor_monotonic = now_monotonic
        state.start_zone_departed = False


def _distance_meters(latitude_a, longitude_a, latitude_b, longitude_b):
    latitude_a_radians = radians(latitude_a)
    longitude_a_radians = radians(longitude_a)
    latitude_b_radians = radians(latitude_b)
    longitude_b_radians = radians(longitude_b)

    latitude_delta = latitude_b_radians - latitude_a_radians
    longitude_delta = longitude_b_radians - longitude_a_radians

    haversine = (
        sin(latitude_delta / 2.0) ** 2
        + cos(latitude_a_radians)
        * cos(latitude_b_radians)
        * sin(longitude_delta / 2.0) ** 2
    )
    central_angle = 2.0 * atan2(sqrt(haversine), sqrt(1.0 - haversine))
    return EARTH_RADIUS_METERS * central_angle
