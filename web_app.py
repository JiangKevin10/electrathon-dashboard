from flask import Flask

def create_app(state):
    app = Flask(__name__)

    @app.route("/")
    def home():
        session_text = "RUNNING" if state.session_active else "IDLE"
        current_file_text = state.current_session_name if state.current_session_name else "None"
        last_file_text = state.last_session_name if state.last_session_name else "None"
        started_text = (
            state.session_started_at.strftime("%Y-%m-%d %H:%M:%S")
            if state.session_started_at
            else "None"
        )
        elapsed_text = f"{state.session_elapsed_seconds:.1f}s" if state.session_active else "0.0s"

        return f"""
        <html>
            <head>
                <title>Electrathon Dashboard</title>
                <meta http-equiv="refresh" content="1">
            </head>
            <body style="font-family: Arial; text-align: center; margin-top: 60px;">
                <h1>Electrathon Dashboard</h1>
                <p>Status: <b>{state.status}</b></p>
                <p>Session: <b>{session_text}</b></p>
                <p>Current Race File: <b>{current_file_text}</b></p>
                <p>Last Race File: <b>{last_file_text}</b></p>
                <p>Session Started: <b>{started_text}</b></p>
                <p>Elapsed: <b>{elapsed_text}</b></p>
                <h2>Current RPM</h2>
                <p style="font-size: 48px;">{state.rpm:.2f}</p>
                <h3>Count</h3>
                <p style="font-size: 32px;">{state.count}</p>
            </body>
        </html>
        """

    return app
