from flask import Flask

def create_app(state):
    app = Flask(__name__)

    @app.route("/")
    def home():
        log_text = "ON" if state.logging_on else "OFF"
        file_text = state.csv_filename if state.csv_filename else "None"

        return f"""
        <html>
            <head>
                <title>Electrathon Dashboard</title>
                <meta http-equiv="refresh" content="1">
            </head>
            <body style="font-family: Arial; text-align: center; margin-top: 60px;">
                <h1>Electrathon Dashboard</h1>
                <p>Status: <b>{state.status}</b></p>
                <p>Logging: <b>{log_text}</b></p>
                <p>CSV File: <b>{file_text}</b></p>
                <h2>Current RPM</h2>
                <p style="font-size: 48px;">{state.rpm:.2f}</p>
                <h3>Count</h3>
                <p style="font-size: 32px;">{state.count}</p>
            </body>
        </html>
        """

    return app