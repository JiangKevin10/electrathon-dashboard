import csv
from datetime import datetime
from html import escape

from flask import Flask, abort, jsonify, url_for

from config import LOG_FOLDER


def _list_race_files():
    LOG_FOLDER.mkdir(parents=True, exist_ok=True)
    return sorted(
        [path for path in LOG_FOLDER.glob("*.csv") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _resolve_race_file(filename):
    if "/" in filename or "\\" in filename:
        abort(404)

    race_file = (LOG_FOLDER / filename).resolve()
    log_root = LOG_FOLDER.resolve()

    try:
        race_file.relative_to(log_root)
    except ValueError:
        abort(404)

    if race_file.suffix.lower() != ".csv" or not race_file.is_file():
        abort(404)

    return race_file


def _live_state_payload(state):
    started_text = (
        state.session_started_at.strftime("%Y-%m-%d %H:%M:%S")
        if state.session_started_at
        else "None"
    )
    elapsed_text = f"{state.session_elapsed_seconds:.1f}s" if state.session_active else "0.0s"

    return {
        "status": state.status,
        "session_text": "RUNNING" if state.session_active else "IDLE",
        "current_session_name": state.current_session_name,
        "last_session_name": state.last_session_name,
        "started_text": started_text,
        "elapsed_text": elapsed_text,
        "rpm_text": f"{state.rpm:.2f}",
        "count_text": str(state.count),
    }

def create_app(state):
    app = Flask(__name__)

    @app.route("/")
    def home():
        live_state = _live_state_payload(state)

        current_file_text = "None"
        if live_state["current_session_name"]:
            current_file_text = (
                f'<a href="{url_for("view_race", filename=live_state["current_session_name"])}">'
                f'{escape(live_state["current_session_name"])}</a>'
            )

        last_file_text = "None"
        if live_state["last_session_name"]:
            last_file_text = (
                f'<a href="{url_for("view_race", filename=live_state["last_session_name"])}">'
                f'{escape(live_state["last_session_name"])}</a>'
            )

        return f"""
        <html>
            <head>
                <title>Electrathon Dashboard</title>
            </head>
            <body style="font-family: Arial; text-align: center; margin-top: 60px;">
                <h1>Electrathon Dashboard</h1>
                <p><a href="{url_for("race_list")}">View Saved Races</a></p>
                <p>Status: <b id="status-text">{escape(live_state["status"])}</b></p>
                <p>Session: <b id="session-text">{escape(live_state["session_text"])}</b></p>
                <p>Current Race File: <b id="current-file">{current_file_text}</b></p>
                <p>Last Race File: <b id="last-file">{last_file_text}</b></p>
                <p>Session Started: <b id="started-text">{escape(live_state["started_text"])}</b></p>
                <p>Elapsed: <b id="elapsed-text">{escape(live_state["elapsed_text"])}</b></p>
                <h2>Current RPM</h2>
                <p id="rpm-text" style="font-size: 48px;">{live_state["rpm_text"]}</p>
                <h3>Count</h3>
                <p id="count-text" style="font-size: 32px;">{live_state["count_text"]}</p>
                <script>
                    const pollIntervalMs = 250;

                    function updateRaceLink(elementId, filename, url) {{
                        const target = document.getElementById(elementId);
                        target.textContent = "";

                        if (filename && url) {{
                            const link = document.createElement("a");
                            link.href = url;
                            link.textContent = filename;
                            target.appendChild(link);
                            return;
                        }}

                        target.textContent = "None";
                    }}

                    let liveRequestInFlight = false;

                    async function refreshLiveState() {{
                        if (liveRequestInFlight) {{
                            return;
                        }}

                        liveRequestInFlight = true;

                        try {{
                            const response = await fetch("{url_for("live_state")}", {{
                                cache: "no-store",
                                headers: {{ "Cache-Control": "no-cache" }}
                            }});

                            if (!response.ok) {{
                                return;
                            }}

                            const data = await response.json();
                            document.getElementById("status-text").textContent = data.status;
                            document.getElementById("session-text").textContent = data.session_text;
                            document.getElementById("started-text").textContent = data.started_text;
                            document.getElementById("elapsed-text").textContent = data.elapsed_text;
                            document.getElementById("rpm-text").textContent = data.rpm_text;
                            document.getElementById("count-text").textContent = data.count_text;
                            updateRaceLink("current-file", data.current_session_name, data.current_session_url);
                            updateRaceLink("last-file", data.last_session_name, data.last_session_url);
                        }} catch (error) {{
                        }} finally {{
                            liveRequestInFlight = false;
                        }}
                    }}

                    refreshLiveState();
                    setInterval(refreshLiveState, pollIntervalMs);
                </script>
            </body>
        </html>
        """

    @app.route("/api/live")
    def live_state():
        live_state = _live_state_payload(state)
        live_state["current_session_url"] = (
            url_for("view_race", filename=live_state["current_session_name"])
            if live_state["current_session_name"]
            else None
        )
        live_state["last_session_url"] = (
            url_for("view_race", filename=live_state["last_session_name"])
            if live_state["last_session_name"]
            else None
        )

        response = jsonify(live_state)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/races")
    def race_list():
        race_files = _list_race_files()

        if race_files:
            race_items = []
            for race_file in race_files:
                race_stat = race_file.stat()
                modified_text = datetime.fromtimestamp(race_stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                race_items.append(
                    f"""
                    <li style="margin-bottom: 12px;">
                        <a href="{url_for("view_race", filename=race_file.name)}">{escape(race_file.name)}</a><br>
                        <small>
                            Modified: {escape(modified_text)}
                            | Size: {race_stat.st_size} bytes
                        </small>
                    </li>
                    """
                )
            race_list_html = f'<ul style="padding-left: 20px;">{"".join(race_items)}</ul>'
        else:
            race_list_html = "<p>No saved races found yet.</p>"

        return f"""
        <html>
            <head>
                <title>Saved Races</title>
            </head>
            <body style="font-family: Arial; margin: 40px auto; max-width: 900px; line-height: 1.5;">
                <p><a href="{url_for("home")}">Back to Dashboard</a></p>
                <h1>Saved Races</h1>
                <p>Folder: <code>{escape(str(LOG_FOLDER))}</code></p>
                {race_list_html}
            </body>
        </html>
        """

    @app.route("/races/<filename>")
    def view_race(filename):
        race_file = _resolve_race_file(filename)

        with race_file.open("r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            rows = list(reader)
            fieldnames = reader.fieldnames or ["timestamp", "elapsed_seconds", "count", "rpm"]

        max_rpm = 0.0
        final_count = 0
        duration = "0.00"

        if rows:
            duration = rows[-1].get("elapsed_seconds", "0.00")
            try:
                final_count = int(rows[-1].get("count", 0))
            except (TypeError, ValueError):
                final_count = 0

            rpm_values = []
            for row in rows:
                try:
                    rpm_values.append(float(row.get("rpm", 0) or 0))
                except (TypeError, ValueError):
                    continue

            if rpm_values:
                max_rpm = max(rpm_values)

        header_html = "".join(
            f"<th style=\"border: 1px solid #ccc; padding: 8px; background: #f3f3f3;\">{escape(column)}</th>"
            for column in fieldnames
        )

        row_html = "".join(
            "<tr>"
            + "".join(
                f"<td style=\"border: 1px solid #ccc; padding: 8px;\">{escape(row.get(column, ''))}</td>"
                for column in fieldnames
            )
            + "</tr>"
            for row in rows
        )

        if not row_html:
            row_html = (
                f"<tr><td colspan=\"{len(fieldnames)}\" style=\"border: 1px solid #ccc; padding: 12px;\">"
                "This race file has no data rows yet."
                "</td></tr>"
            )

        return f"""
        <html>
            <head>
                <title>{escape(race_file.name)}</title>
            </head>
            <body style="font-family: Arial; margin: 40px auto; max-width: 1100px; line-height: 1.5;">
                <p><a href="{url_for("home")}">Dashboard</a> | <a href="{url_for("race_list")}">Saved Races</a></p>
                <h1>{escape(race_file.name)}</h1>
                <p><b>Rows:</b> {len(rows)}</p>
                <p><b>Duration:</b> {escape(str(duration))} seconds</p>
                <p><b>Final Count:</b> {final_count}</p>
                <p><b>Max RPM:</b> {max_rpm:.2f}</p>
                <div style="overflow-x: auto;">
                    <table style="border-collapse: collapse; width: 100%;">
                        <thead>
                            <tr>{header_html}</tr>
                        </thead>
                        <tbody>
                            {row_html}
                        </tbody>
                    </table>
                </div>
            </body>
        </html>
        """

    return app
