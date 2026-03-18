class SharedState:
    def __init__(self):
        self.count = 0
        self.rpm = 0.0
        self.logging_on = False
        self.status = "Starting..."
        self.csv_filename = None