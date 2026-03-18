import threading
from shared_state import SharedState
from serial_worker import run_serial_worker
from web_app import create_app

state = SharedState()

thread = threading.Thread(target=run_serial_worker, args=(state,), daemon=True)
thread.start()

app = create_app(state)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)