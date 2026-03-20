class SharedState:
    def __init__(self):
        self.count = 0
        self.rpm = 0.0
        self.gps_latitude = None
        self.gps_longitude = None
        self.gps_has_fix = False
        self.gps_satellites = 0
        self.gps_utc_date = None
        self.gps_utc_time = None
        self.last_raw_gps_line = "Waiting for GPS serial data"
        self.last_raw_gpstime_line = "Waiting for GPS time data"
        self.session_requested = False
        self.session_active = False
        self.status = "Starting..."
        self.current_session_filename = None
        self.current_session_name = None
        self.last_session_filename = None
        self.last_session_name = None
        self.session_started_at = None
        self.session_started_monotonic = None
        self.session_elapsed_seconds = 0.0
        self.live_route_points = []
