import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def default_serial_port():
    configured_port = os.getenv("ELECTRATHON_PORT")
    if configured_port:
        return configured_port

    if os.name == "nt":
        return "COM5"

    for pattern in ("ttyUSB*", "ttyACM*"):
        matches = sorted(Path("/dev").glob(pattern))
        if matches:
            return str(matches[0])

    return "/dev/ttyUSB0"


PORT = default_serial_port()
BAUD = int(os.getenv("ELECTRATHON_BAUD", "115200"))
MAGNETS_PER_REV = int(os.getenv("ELECTRATHON_MAGNETS_PER_REV", "1"))
LOG_FOLDER = Path(
    os.getenv("ELECTRATHON_LOG_FOLDER", str(BASE_DIR / "CSV-LOGS"))
)
RAW_LOG_FOLDER = Path(
    os.getenv("ELECTRATHON_RAW_LOG_FOLDER", str(BASE_DIR / "RAW-RACE-LOGS"))
)
