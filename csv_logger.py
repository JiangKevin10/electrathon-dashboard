import csv
import os
from datetime import datetime
from config import LOG_FOLDER

os.makedirs(LOG_FOLDER, exist_ok=True)

csv_file = None
csv_writer = None

def start_csv(state):
    global csv_file, csv_writer

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = os.path.join(LOG_FOLDER, f"ride_log_{timestamp}.csv")

    csv_file = open(filename, "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["timestamp", "count", "rpm"])

    state.csv_filename = filename
    print(f"Logging started -> {filename}")

def write_row(state):
    global csv_file, csv_writer

    if csv_writer:
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        csv_writer.writerow([timestamp_str, state.count, round(state.rpm, 2)])
        csv_file.flush()

def stop_csv():
    global csv_file, csv_writer

    if csv_file:
        csv_file.close()
        csv_file = None
        csv_writer = None
        print("Logging stopped")