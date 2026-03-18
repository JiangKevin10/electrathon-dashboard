import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

PORT = os.getenv("ELECTRATHON_PORT", "/dev/ttyACM0")
BAUD = int(os.getenv("ELECTRATHON_BAUD", "9600"))
MAGNETS_PER_REV = int(os.getenv("ELECTRATHON_MAGNETS_PER_REV", "1"))
LOG_FOLDER = Path(
    os.getenv("ELECTRATHON_LOG_FOLDER", str(BASE_DIR / "CSV-LOGS"))
)
