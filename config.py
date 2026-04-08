import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

PORT = os.getenv("ELECTRATHON_PORT", "/dev/ttyACM0")
BAUD = int(os.getenv("ELECTRATHON_BAUD", "115200"))
MAGNETS_PER_REV = int(os.getenv("ELECTRATHON_MAGNETS_PER_REV", "1"))
WHEEL_DIAMETER_METERS = float(os.getenv("ELECTRATHON_WHEEL_DIAMETER_METERS", "0"))
ROUTE_BLEND_WEIGHT = float(os.getenv("ELECTRATHON_ROUTE_BLEND_WEIGHT", "0.5"))
INITIAL_HEADING_DISTANCE_METERS = float(
    os.getenv("ELECTRATHON_INITIAL_HEADING_DISTANCE_METERS", "2.0")
)
LOG_FOLDER = Path(
    os.getenv("ELECTRATHON_LOG_FOLDER", str(BASE_DIR / "CSV-LOGS"))
)
RAW_LOG_FOLDER = Path(
    os.getenv("ELECTRATHON_RAW_LOG_FOLDER", str(BASE_DIR / "RAW-RACE-LOGS"))
)
