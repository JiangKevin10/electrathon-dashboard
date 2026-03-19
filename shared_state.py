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
        self.pps_enabled = True
        self.pps_locked = False
        self.pps_pulse_count = 0
        self.pps_age_ms = None
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
