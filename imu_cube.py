import argparse
import math
import queue
import threading
import time
import tkinter as tk

import serial

from config import BAUD, PORT


WIDTH = 760
HEIGHT = 560
STATUS_HEIGHT = 64
BUTTON_WIDTH = 104
BUTTON_HEIGHT = 30
BUTTON_GAP = 8
FOV = 520
CUBE_SIZE = 130

VERTICES = [
    (-1, -1, -1),
    (1, -1, -1),
    (1, 1, -1),
    (-1, 1, -1),
    (-1, -1, 1),
    (1, -1, 1),
    (1, 1, 1),
    (-1, 1, 1),
]

EDGES = [
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 0),
    (4, 5),
    (5, 6),
    (6, 7),
    (7, 4),
    (0, 4),
    (1, 5),
    (2, 6),
    (3, 7),
]

FACES = [
    (0, 1, 2, 3, "#3254a8"),
    (4, 5, 6, 7, "#f2b84b"),
    (0, 1, 5, 4, "#2f9d69"),
    (2, 3, 7, 6, "#d94f45"),
    (1, 2, 6, 5, "#7d5cc6"),
    (0, 3, 7, 4, "#4c9ec4"),
]


def parse_imu_line(line):
    if not line.startswith("IMU:"):
        return None

    parts = line.strip().split(":", 1)[1].split(",")
    if len(parts) < 4:
        return None

    try:
        heading = float(parts[0])
        pitch = float(parts[1])
        roll = float(parts[2])
        yaw_rate = float(parts[3])
    except ValueError:
        return None

    ok = True
    if len(parts) >= 5:
        try:
            ok = int(float(parts[4])) == 1
        except ValueError:
            ok = parts[4].strip().lower() in {"true", "ok"}

    return heading, pitch, roll, yaw_rate, ok


def serial_reader(port, baud, output_queue, stop_event):
    while not stop_event.is_set():
        try:
            with serial.Serial(port, baud, timeout=0.2) as ser:
                output_queue.put(("status", f"Connected to {port} at {baud} baud"))
                while not stop_event.is_set():
                    raw_line = ser.readline()
                    if not raw_line:
                        continue

                    try:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                    except UnicodeDecodeError:
                        continue

                    imu_data = parse_imu_line(line)
                    if imu_data:
                        output_queue.put(("imu", imu_data))
                    else:
                        output_queue.put(("raw", line))
        except serial.SerialException as exc:
            output_queue.put(("status", f"Serial error: {exc}"))
            time.sleep(1.0)


def mat_mul(left, right):
    return [
        [
            sum(left[row][index] * right[index][col] for index in range(3))
            for col in range(3)
        ]
        for row in range(3)
    ]


def mat_vec_mul(matrix, vector):
    x, y, z = vector
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z,
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z,
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z,
    )


def mat_transpose(matrix):
    return [
        [matrix[0][0], matrix[1][0], matrix[2][0]],
        [matrix[0][1], matrix[1][1], matrix[2][1]],
        [matrix[0][2], matrix[1][2], matrix[2][2]],
    ]


def orientation_matrix(heading_deg, pitch_deg, roll_deg):
    heading = math.radians(heading_deg)
    pitch = math.radians(pitch_deg)
    roll = math.radians(roll_deg)

    ch = math.cos(heading)
    sh = math.sin(heading)
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    cr = math.cos(roll)
    sr = math.sin(roll)

    yaw_matrix = [
        [ch, -sh, 0.0],
        [sh, ch, 0.0],
        [0.0, 0.0, 1.0],
    ]
    pitch_matrix = [
        [cp, 0.0, sp],
        [0.0, 1.0, 0.0],
        [-sp, 0.0, cp],
    ]
    roll_matrix = [
        [1.0, 0.0, 0.0],
        [0.0, cr, -sr],
        [0.0, sr, cr],
    ]

    return mat_mul(yaw_matrix, mat_mul(pitch_matrix, roll_matrix))


def rotate_point(point, matrix):
    x, y, z = mat_vec_mul(matrix, point)

    return x * CUBE_SIZE, y * CUBE_SIZE, z * CUBE_SIZE


def project_point(point):
    x, y, z = point
    z_offset = z + 520
    scale = FOV / max(120, z_offset)
    return WIDTH / 2 + x * scale, (HEIGHT + STATUS_HEIGHT) / 2 - y * scale


class ImuCubeApp:
    def __init__(self, root, data_queue):
        self.root = root
        self.data_queue = data_queue
        self.heading = 0.0
        self.pitch = 0.0
        self.roll = 0.0
        self.yaw_rate = 0.0
        self.imu_ok = False
        self.home_inverse_matrix = orientation_matrix(0.0, 0.0, 0.0)
        self.status = "Waiting for IMU serial data"
        self.last_raw_line = ""
        self.last_imu_time = 0.0
        self.buttons = []

        self.root.title("Electrathon IMU Cube")
        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, bg="#101318", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.handle_click)
        self.root.bind("<space>", lambda event: self.set_home_pose())
        self.root.bind("<h>", lambda event: self.set_home_heading())
        self.root.bind("<H>", lambda event: self.set_home_heading())
        self.root.bind("<c>", lambda event: self.clear_home())
        self.root.bind("<C>", lambda event: self.clear_home())

        self.root.after(16, self.tick)

    def handle_click(self, event):
        for button in self.buttons:
            left, top, right, bottom = button["bounds"]
            if left <= event.x <= right and top <= event.y <= bottom:
                button["command"]()
                return

    def current_orientation_matrix(self):
        return orientation_matrix(self.heading, self.pitch, self.roll)

    def set_home_pose(self):
        self.home_inverse_matrix = mat_transpose(self.current_orientation_matrix())
        self.status = "Home set to current heading, pitch, and roll"

    def set_home_heading(self):
        self.home_inverse_matrix = mat_transpose(orientation_matrix(self.heading, 0.0, 0.0))
        self.status = "Home set to current heading only"

    def clear_home(self):
        self.home_inverse_matrix = orientation_matrix(0.0, 0.0, 0.0)
        self.status = "Home orientation cleared"

    def tick(self):
        self.drain_queue()
        self.draw()
        self.root.after(16, self.tick)

    def drain_queue(self):
        while True:
            try:
                message_type, payload = self.data_queue.get_nowait()
            except queue.Empty:
                break

            if message_type == "imu":
                self.heading, self.pitch, self.roll, self.yaw_rate, self.imu_ok = payload
                self.last_imu_time = time.time()
            elif message_type == "status":
                self.status = payload
            elif message_type == "raw":
                self.last_raw_line = payload

    def draw(self):
        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, WIDTH, HEIGHT, fill="#101318", outline="")
        self.canvas.create_rectangle(0, HEIGHT - STATUS_HEIGHT, WIDTH, HEIGHT, fill="#181d24", outline="")

        current_matrix = self.current_orientation_matrix()
        display_matrix = mat_mul(self.home_inverse_matrix, current_matrix)
        display_heading = self.heading
        display_pitch = self.pitch
        display_roll = self.roll

        rotated = [rotate_point(vertex, display_matrix) for vertex in VERTICES]
        projected = [project_point(vertex) for vertex in rotated]

        face_depths = []
        for face in FACES:
            depth = sum(rotated[index][2] for index in face[:4]) / 4.0
            face_depths.append((depth, face))

        for _, face in sorted(face_depths, reverse=True):
            indices = face[:4]
            color = face[4]
            coords = []
            for index in indices:
                coords.extend(projected[index])
            self.canvas.create_polygon(coords, fill=color, outline="#e8edf2", width=2)

        for start, end in EDGES:
            self.canvas.create_line(
                projected[start][0],
                projected[start][1],
                projected[end][0],
                projected[end][1],
                fill="#f7f7f7",
                width=2,
            )

        stale = time.time() - self.last_imu_time > 2.0
        imu_state = "OK" if self.imu_ok and not stale else "WAITING"
        text = (
            f"heading {display_heading:6.2f}   pitch {display_pitch:6.2f}   "
            f"roll {display_roll:6.2f}   yaw rate {self.yaw_rate:6.2f} dps   {imu_state}"
        )
        self.canvas.create_text(18, HEIGHT - 42, anchor="w", fill="#f4f7fb", font=("Segoe UI", 13), text=text)
        self.canvas.create_text(18, HEIGHT - 18, anchor="w", fill="#9ca8b7", font=("Segoe UI", 10), text=self.status)

        self.draw_buttons()

        if self.last_raw_line and stale:
            self.canvas.create_text(
                WIDTH - 18,
                HEIGHT - 18,
                anchor="e",
                fill="#9ca8b7",
                font=("Segoe UI", 10),
                text=self.last_raw_line[:72],
            )

    def draw_buttons(self):
        controls = [
            ("Set Pose", self.set_home_pose),
            ("Set Heading", self.set_home_heading),
            ("Clear", self.clear_home),
        ]
        canvas_width = self.canvas.winfo_width()
        total_width = len(controls) * BUTTON_WIDTH + (len(controls) - 1) * BUTTON_GAP
        left = canvas_width - total_width - 18
        top = 18
        self.buttons = []

        for index, (label, command) in enumerate(controls):
            button_left = left + index * (BUTTON_WIDTH + BUTTON_GAP)
            button_right = button_left + BUTTON_WIDTH
            button_bottom = top + BUTTON_HEIGHT
            self.buttons.append(
                {
                    "bounds": (button_left, top, button_right, button_bottom),
                    "command": command,
                }
            )
            self.canvas.create_rectangle(
                button_left,
                top,
                button_right,
                button_bottom,
                fill="#26313d",
                outline="#9ca8b7",
                width=1,
            )
            self.canvas.create_text(
                (button_left + button_right) / 2,
                (top + button_bottom) / 2,
                fill="#f4f7fb",
                font=("Segoe UI", 10),
                text=label,
            )


def main():
    parser = argparse.ArgumentParser(description="Show BNO08X IMU orientation as a 3D cube.")
    parser.add_argument("--port", default=PORT, help=f"Serial port, default from ELECTRATHON_PORT or {PORT}")
    parser.add_argument("--baud", type=int, default=BAUD, help=f"Serial baud, default {BAUD}")
    args = parser.parse_args()

    data_queue = queue.Queue()
    stop_event = threading.Event()
    reader = threading.Thread(
        target=serial_reader,
        args=(args.port, args.baud, data_queue, stop_event),
        daemon=True,
    )
    reader.start()

    root = tk.Tk()
    ImuCubeApp(root, data_queue)

    try:
        root.mainloop()
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
