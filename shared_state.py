class SharedState:
    def __init__(self):
        self.count = 0
        self.rpm = 0.0
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
