import csv
import time
from datetime import datetime

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template_string,
    request,
    url_for,
)

from config import LOG_FOLDER
from lap_tracker import clear_start_zone, configure_start_zone, has_start_zone

CLEAR_HISTORY_PASSWORD = "lymanpassword"
HIDDEN_RACE_COLUMNS = {"pps_locked", "pps_pulse_count", "pps_age_ms"}
HOME_TEMPLATE = """
<!doctype html>
<html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Electrathon Dashboard</title>
        <link
            rel="stylesheet"
            href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
            integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
            crossorigin=""
        >
        <style>
            :root {
                color-scheme: light;
                --bg: #eef3f8;
                --card: #ffffff;
                --border: #cfd9e4;
                --text: #17324d;
                --muted: #5f748a;
                --accent: #1565c0;
                --accent-soft: #d9ebff;
            }

            * {
                box-sizing: border-box;
            }

            body {
                margin: 0;
                font-family: "Segoe UI", Tahoma, sans-serif;
                background: linear-gradient(180deg, #f7fafc 0%, var(--bg) 100%);
                color: var(--text);
            }

            a {
                color: var(--accent);
            }

            .page {
                max-width: 1180px;
                margin: 0 auto;
                padding: 28px 20px 36px;
            }

            .page-header {
                display: flex;
                flex-wrap: wrap;
                gap: 12px;
                justify-content: space-between;
                align-items: flex-start;
                margin-bottom: 20px;
            }

            .page-header h1 {
                margin: 0 0 6px;
            }

            .page-header p {
                margin: 0;
                color: var(--muted);
            }

            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
                gap: 14px;
                margin-bottom: 18px;
            }

            .card {
                background: var(--card);
                border: 1px solid var(--border);
                border-radius: 14px;
                padding: 18px;
                box-shadow: 0 8px 24px rgba(25, 50, 75, 0.06);
            }

            .card h2,
            .card h3 {
                margin: 0 0 10px;
                font-size: 1rem;
            }

            .stat-value {
                font-size: 2.2rem;
                font-weight: 700;
                line-height: 1.1;
            }

            .meta {
                color: var(--muted);
                font-size: 0.95rem;
            }

            .map-card {
                margin-bottom: 18px;
            }

            .map-toolbar {
                display: flex;
                flex-wrap: wrap;
                justify-content: space-between;
                align-items: center;
                gap: 12px;
                margin-bottom: 12px;
            }

            .map-status {
                color: var(--muted);
                font-size: 0.95rem;
            }

            .map-action {
                border: 1px solid #8ab4e6;
                background: var(--accent-soft);
                color: var(--accent);
                border-radius: 999px;
                padding: 8px 14px;
                font: inherit;
                cursor: pointer;
            }

            #route-map {
                width: 100%;
                height: 380px;
                border-radius: 12px;
                overflow: hidden;
                border: 1px solid var(--border);
            }

            .details-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: 14px;
            }

            .detail-line {
                margin: 0 0 8px;
            }

            label,
            input,
            button {
                font: inherit;
            }

            .field-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                gap: 10px 12px;
                margin: 12px 0;
                align-items: end;
            }

            .field-grid label {
                display: block;
                margin-bottom: 6px;
                font-weight: 600;
            }

            .field-grid input {
                width: 100%;
                padding: 9px 10px;
                border: 1px solid var(--border);
                border-radius: 8px;
            }

            .action-row {
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                margin: 12px 0 10px;
            }

            .secondary-action {
                border-color: var(--border);
                background: #f7fafc;
                color: var(--text);
            }

            code {
                white-space: pre-wrap;
                word-break: break-word;
            }
        </style>
    </head>
    <body>
        <main class="page">
            <header class="page-header">
                <div>
                    <h1>Electrathon Dashboard</h1>
                    <p>Live RPM, lap count, GPS status, and route tracking.</p>
                </div>
                <p><a href="{{ url_for('race_list') }}">View Saved Races</a></p>
            </header>

            <section class="stats-grid">
                <article class="card">
                    <h2>Status</h2>
                    <p class="detail-line">Serial: <b id="status-text">{{ live_state.status }}</b></p>
                    <p class="detail-line">Session: <b id="session-text">{{ live_state.session_text }}</b></p>
                    <p class="detail-line">
                        Current Race File:
                        <b id="current-file">
                            {% if live_state.current_session_name and live_state.current_session_url %}
                                <a href="{{ live_state.current_session_url }}">{{ live_state.current_session_name }}</a>
                            {% else %}
                                None
                            {% endif %}
                        </b>
                    </p>
                    <p class="detail-line">
                        Last Race File:
                        <b id="last-file">
                            {% if live_state.last_session_name and live_state.last_session_url %}
                                <a href="{{ live_state.last_session_url }}">{{ live_state.last_session_name }}</a>
                            {% else %}
                                None
                            {% endif %}
                        </b>
                    </p>
                </article>

                <article class="card">
                    <h2>RPM</h2>
                    <p class="stat-value" id="rpm-text">{{ live_state.rpm_text }}</p>
                    <p class="meta">Count: <b id="count-text">{{ live_state.count_text }}</b></p>
                </article>

                <article class="card">
                    <h2>Session Timing</h2>
                    <p class="detail-line">Started: <b id="started-text">{{ live_state.started_text }}</b></p>
                    <p class="detail-line">Elapsed: <b id="elapsed-text">{{ live_state.elapsed_text }}</b></p>
                </article>

                <article class="card">
                    <h2>Laps</h2>
                    <p class="stat-value" id="lap-count-text">{{ live_state.lap_count_text }}</p>
                    <p class="meta">Last Lap: <b id="last-lap-text">{{ live_state.last_lap_text }}</b></p>
                    <p class="meta">Zone: <b id="start-zone-status-text">{{ live_state.start_zone_status_text }}</b></p>
                </article>

                <article class="card">
                    <h2>GPS</h2>
                    <p class="detail-line">Status: <b id="gps-status-text">{{ live_state.gps_status_text }}</b></p>
                    <p class="detail-line">Latitude: <b id="gps-latitude-text">{{ live_state.gps_latitude_text }}</b></p>
                    <p class="detail-line">Longitude: <b id="gps-longitude-text">{{ live_state.gps_longitude_text }}</b></p>
                    <p class="detail-line">UTC Time: <b id="gps-time-text">{{ live_state.gps_time_text }}</b></p>
                    <p class="detail-line">
                        <a
                            id="gps-map-link"
                            href="{{ live_state.gps_maps_url or '#' }}"
                            target="_blank"
                            rel="noopener noreferrer"
                            {% if not live_state.gps_maps_url %}style="display: none;"{% endif %}
                        >
                            Open current position in Google Maps
                        </a>
                    </p>
                </article>
            </section>

            <section class="card map-card">
                <div class="map-toolbar">
                    <div>
                        <h2 style="margin: 0 0 6px;">Live Route Map</h2>
                        <div class="map-status" id="route-map-status">Waiting for GPS route data.</div>
                    </div>
                    <button class="map-action" id="recenter-route" type="button">Recenter Route</button>
                </div>
                <div id="route-map"></div>
            </section>

            <section class="details-grid">
                <article class="card">
                    <h3>Start / Finish Zone</h3>
                    <p class="detail-line">Center: <b id="start-zone-center-text">{{ live_state.start_zone_center_text }}</b></p>
                    <p class="detail-line">Radius: <b id="start-zone-radius-text">{{ live_state.start_zone_radius_text }}</b></p>
                    <p class="detail-line">Minimum Lap Time: <b id="minimum-lap-text">{{ live_state.minimum_lap_text }}</b></p>
                    <div class="field-grid">
                        <div>
                            <label for="start-zone-radius-input">Radius (meters)</label>
                            <input
                                id="start-zone-radius-input"
                                type="number"
                                min="1"
                                step="1"
                                value="{{ live_state.start_zone_radius_value }}"
                            >
                        </div>
                        <div>
                            <label for="minimum-lap-seconds-input">Minimum Lap Time (seconds)</label>
                            <input
                                id="minimum-lap-seconds-input"
                                type="number"
                                min="1"
                                step="1"
                                value="{{ live_state.minimum_lap_seconds_value }}"
                            >
                        </div>
                    </div>
                    <div class="action-row">
                        <button class="map-action" id="set-start-zone" type="button">Set Start Here</button>
                        <button class="map-action secondary-action" id="clear-start-zone" type="button">Clear Start</button>
                    </div>
                    <p class="meta" id="start-zone-action-text">Use the current GPS fix to place the start zone.</p>
                </article>

                <article class="card">
                    <h3>Raw GPS Serial</h3>
                    <p class="detail-line">GPS: <code id="raw-gps-line">{{ live_state.last_raw_gps_line }}</code></p>
                    <p class="detail-line">GPSTIME: <code id="raw-gpstime-line">{{ live_state.last_raw_gpstime_line }}</code></p>
                </article>
            </section>
        </main>

        <script
            src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
            integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
            crossorigin=""
        ></script>
        {{ route_map_script|safe }}
        <script>
            const liveStateUrl = {{ url_for("live_state")|tojson }};
            const liveRouteUrl = {{ url_for("live_route")|tojson }};
            const setStartZoneUrl = {{ url_for("set_start_zone")|tojson }};
            const clearStartZoneUrl = {{ url_for("clear_start_zone_route")|tojson }};
            const routeMap = createRouteMap({
                containerId: "route-map",
                statusId: "route-map-status",
                pointsLabel: "route points"
            });

            let lastRouteState = {{ route_state|tojson }};
            routeMap.render(lastRouteState, { forceFit: true });

            document.getElementById("recenter-route").addEventListener("click", function () {
                routeMap.recenterToRoute(lastRouteState);
            });

            function updateRaceLink(elementId, filename, url) {
                const target = document.getElementById(elementId);
                target.replaceChildren();

                if (filename && url) {
                    const link = document.createElement("a");
                    link.href = url;
                    link.textContent = filename;
                    target.appendChild(link);
                    return;
                }

                target.textContent = "None";
            }

            function updateGpsLink(url) {
                const gpsLink = document.getElementById("gps-map-link");
                if (url) {
                    gpsLink.href = url;
                    gpsLink.style.display = "inline";
                    return;
                }

                gpsLink.removeAttribute("href");
                gpsLink.style.display = "none";
            }

            function syncNumberInput(elementId, value) {
                const input = document.getElementById(elementId);
                const nextValue = String(value);
                if (document.activeElement !== input && input.value !== nextValue) {
                    input.value = nextValue;
                }
            }

            function setStartZoneActionText(text, isError) {
                const target = document.getElementById("start-zone-action-text");
                target.textContent = text;
                target.style.color = isError ? "#8d1b1b" : "";
            }

            function applyLiveState(data, options) {
                const opts = options || {};
                document.getElementById("status-text").textContent = data.status;
                document.getElementById("session-text").textContent = data.session_text;
                document.getElementById("started-text").textContent = data.started_text;
                document.getElementById("elapsed-text").textContent = data.elapsed_text;
                document.getElementById("rpm-text").textContent = data.rpm_text;
                document.getElementById("count-text").textContent = data.count_text;
                document.getElementById("lap-count-text").textContent = data.lap_count_text;
                document.getElementById("last-lap-text").textContent = data.last_lap_text;
                document.getElementById("start-zone-status-text").textContent = data.start_zone_status_text;
                document.getElementById("gps-status-text").textContent = data.gps_status_text;
                document.getElementById("gps-latitude-text").textContent = data.gps_latitude_text;
                document.getElementById("gps-longitude-text").textContent = data.gps_longitude_text;
                document.getElementById("gps-time-text").textContent = data.gps_time_text;
                document.getElementById("start-zone-center-text").textContent = data.start_zone_center_text;
                document.getElementById("start-zone-radius-text").textContent = data.start_zone_radius_text;
                document.getElementById("minimum-lap-text").textContent = data.minimum_lap_text;
                document.getElementById("raw-gps-line").textContent = data.last_raw_gps_line;
                document.getElementById("raw-gpstime-line").textContent = data.last_raw_gpstime_line;
                updateRaceLink("current-file", data.current_session_name, data.current_session_url);
                updateRaceLink("last-file", data.last_session_name, data.last_session_url);
                updateGpsLink(data.gps_maps_url);
                if (opts.syncControls) {
                    syncNumberInput("start-zone-radius-input", data.start_zone_radius_value);
                    syncNumberInput("minimum-lap-seconds-input", data.minimum_lap_seconds_value);
                }
            }

            function readPositiveNumber(elementId) {
                const parsedValue = Number.parseFloat(document.getElementById(elementId).value);
                if (!Number.isFinite(parsedValue) || parsedValue <= 0) {
                    return null;
                }

                return parsedValue;
            }

            let liveStateRequestInFlight = false;
            let liveRouteRequestInFlight = false;

            async function refreshLiveState() {
                if (liveStateRequestInFlight) {
                    return;
                }

                liveStateRequestInFlight = true;

                try {
                    const response = await fetch(liveStateUrl, {
                        cache: "no-store",
                        headers: { "Cache-Control": "no-cache" }
                    });
                    if (!response.ok) {
                        return;
                    }

                    const data = await response.json();
                    applyLiveState(data);
                } catch (error) {
                } finally {
                    liveStateRequestInFlight = false;
                }
            }

            async function refreshLiveRoute() {
                if (liveRouteRequestInFlight) {
                    return;
                }

                liveRouteRequestInFlight = true;

                try {
                    const response = await fetch(liveRouteUrl, {
                        cache: "no-store",
                        headers: { "Cache-Control": "no-cache" }
                    });
                    if (!response.ok) {
                        return;
                    }

                    lastRouteState = await response.json();
                    routeMap.render(lastRouteState);
                } catch (error) {
                } finally {
                    liveRouteRequestInFlight = false;
                }
            }

            async function sendStartZoneRequest(url, body, successMessage) {
                const requestOptions = {
                    method: "POST",
                    headers: {}
                };
                if (body !== undefined) {
                    requestOptions.headers["Content-Type"] = "application/json";
                    requestOptions.body = JSON.stringify(body);
                }

                try {
                    const response = await fetch(url, requestOptions);
                    const payload = await response.json().catch(function () {
                        return {};
                    });

                    if (!response.ok) {
                        throw new Error(payload.error || "Request failed.");
                    }

                    applyLiveState(payload.live_state, { syncControls: true });
                    lastRouteState = payload.route_state;
                    routeMap.render(lastRouteState, { forceFit: true });
                    setStartZoneActionText(successMessage, false);
                } catch (error) {
                    setStartZoneActionText(error.message || "Request failed.", true);
                }
            }

            document.getElementById("set-start-zone").addEventListener("click", function () {
                const radiusMeters = readPositiveNumber("start-zone-radius-input");
                const minimumLapSeconds = readPositiveNumber("minimum-lap-seconds-input");
                if (radiusMeters === null || minimumLapSeconds === null) {
                    setStartZoneActionText("Enter a positive radius and minimum lap time.", true);
                    return;
                }

                sendStartZoneRequest(
                    setStartZoneUrl,
                    {
                        radius_meters: radiusMeters,
                        minimum_lap_seconds: minimumLapSeconds
                    },
                    "Start zone updated from the current GPS fix."
                );
            });

            document.getElementById("clear-start-zone").addEventListener("click", function () {
                sendStartZoneRequest(
                    clearStartZoneUrl,
                    undefined,
                    "Start zone cleared."
                );
            });

            setInterval(refreshLiveState, 250);
            setInterval(refreshLiveRoute, 1000);
        </script>
    </body>
</html>
"""
ROUTE_MAP_SCRIPT = """
<script>
    function createRouteMap(options) {
        function isValidPoint(point) {
            return point && Number.isFinite(point.latitude) && Number.isFinite(point.longitude);
        }

        function toLatLng(point) {
            return [point.latitude, point.longitude];
        }

        function removeLayerIfPresent(map, layer) {
            if (map.hasLayer(layer)) {
                map.removeLayer(layer);
            }
        }

        function setMarker(map, marker, latLng, label) {
            marker.setLatLng(latLng);
            marker.bindTooltip(label, { permanent: false, direction: "top" });
            if (!map.hasLayer(marker)) {
                marker.addTo(map);
            }
        }

        function buildStatusText(data, pointCount) {
            if (pointCount > 1) {
                if (data && data.session_active && data.gps_has_fix) {
                    return pointCount + " route points captured. Live route is updating.";
                }

                if (data && data.session_active) {
                    return pointCount + " route points captured. Waiting for the next GPS fix.";
                }

                return pointCount + " route points captured for this saved run.";
            }

            if (pointCount === 1) {
                return "Only one GPS point has been captured so far.";
            }

            if (isValidPoint(data && data.current_position)) {
                return "Showing the latest GPS position.";
            }

            return "Waiting for GPS route data.";
        }

        function hasHoverDetails(point) {
            return Boolean(
                point
                && (
                    Number.isFinite(point.elapsed_seconds)
                    || Number.isFinite(point.rpm)
                    || Number.isFinite(point.count)
                    || (typeof point.timestamp === "string" && point.timestamp)
                )
            );
        }

        function escapeHtml(value) {
            return String(value).replace(/[&<>"']/g, function (char) {
                return {
                    "&": "&amp;",
                    "<": "&lt;",
                    ">": "&gt;",
                    '"': "&quot;",
                    "'": "&#39;"
                }[char];
            });
        }

        function buildPointTooltip(point) {
            const lines = [];

            if (Number.isFinite(point.elapsed_seconds)) {
                lines.push("<b>Elapsed:</b> " + point.elapsed_seconds.toFixed(1) + "s");
            }

            if (Number.isFinite(point.rpm)) {
                lines.push("<b>RPM:</b> " + point.rpm.toFixed(2));
            }

            if (Number.isFinite(point.count)) {
                lines.push("<b>Count:</b> " + point.count);
            }

            if (typeof point.timestamp === "string" && point.timestamp) {
                lines.push("<b>Recorded:</b> " + escapeHtml(point.timestamp));
            }

            return lines.join("<br>");
        }

        const statusElement = document.getElementById(options.statusId);
        const map = L.map(options.containerId, {
            zoomControl: true,
            scrollWheelZoom: true
        });

        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        }).addTo(map);

        const routeLine = L.polyline([], {
            color: "#1565c0",
            weight: 6,
            lineCap: "round",
            lineJoin: "round",
            opacity: 0.9
        }).addTo(map);

        const startMarker = L.circleMarker([0, 0], {
            radius: 7,
            color: "#2e7d32",
            fillColor: "#66bb6a",
            fillOpacity: 0.95
        });

        const endMarker = L.circleMarker([0, 0], {
            radius: 7,
            color: "#c62828",
            fillColor: "#ef5350",
            fillOpacity: 0.95
        });

        const currentMarker = L.circleMarker([0, 0], {
            radius: 8,
            color: "#f57c00",
            fillColor: "#ffb74d",
            fillOpacity: 0.95
        });

        const startZoneCircle = L.circle([0, 0], {
            radius: 0,
            color: "#2e7d32",
            fillColor: "#66bb6a",
            fillOpacity: 0.12,
            weight: 2
        });

        const hoverMarker = L.circleMarker([0, 0], {
            radius: 6,
            color: "#0d47a1",
            fillColor: "#42a5f5",
            fillOpacity: 0.95,
            weight: 2,
            interactive: false
        });

        let followRoute = true;
        let hasView = false;
        let hoverPoints = [];
        let hoverEnabled = false;

        map.on("dragstart", function () {
            followRoute = false;
        });

        map.on("zoomstart", function () {
            followRoute = false;
            removeLayerIfPresent(map, hoverMarker);
        });

        function hideHoverMarker() {
            removeLayerIfPresent(map, hoverMarker);
        }

        function findNearestPoint(latlng) {
            if (!hoverEnabled || !hoverPoints.length) {
                return null;
            }

            const mousePoint = map.latLngToLayerPoint(latlng);
            let nearestPoint = null;
            let nearestDistance = Infinity;

            for (const point of hoverPoints) {
                const pointPixel = map.latLngToLayerPoint([point.latitude, point.longitude]);
                const distance = mousePoint.distanceTo(pointPixel);

                if (distance < nearestDistance) {
                    nearestPoint = point;
                    nearestDistance = distance;
                }
            }

            if (nearestDistance > 18) {
                return null;
            }

            return nearestPoint;
        }

        function updateHoverMarker(latlng) {
            const point = findNearestPoint(latlng);
            if (!point) {
                hideHoverMarker();
                return;
            }

            const tooltipHtml = buildPointTooltip(point);
            if (!tooltipHtml) {
                hideHoverMarker();
                return;
            }

            hoverMarker.setLatLng([point.latitude, point.longitude]);

            if (hoverMarker.getTooltip()) {
                hoverMarker.setTooltipContent(tooltipHtml);
            } else {
                hoverMarker.bindTooltip(tooltipHtml, {
                    permanent: false,
                    direction: "top",
                    opacity: 0.95
                });
            }

            if (!map.hasLayer(hoverMarker)) {
                hoverMarker.addTo(map);
            }

            hoverMarker.openTooltip();
        }

        routeLine.on("mousemove", function (event) {
            updateHoverMarker(event.latlng);
        });
        routeLine.on("mouseout", hideHoverMarker);

        function fitMap(latLngs, currentLatLng, startZoneLatLng, forceFit) {
            if (!(forceFit || followRoute || !hasView)) {
                return;
            }

            if (latLngs.length > 1) {
                map.fitBounds(routeLine.getBounds(), { padding: [24, 24] });
                hasView = true;
                return;
            }

            if (latLngs.length === 1) {
                map.setView(latLngs[0], 17);
                hasView = true;
                return;
            }

            if (currentLatLng) {
                map.setView(currentLatLng, 17);
                hasView = true;
                return;
            }

            if (startZoneLatLng) {
                map.setView(startZoneLatLng, 17);
                hasView = true;
                return;
            }

            if (!hasView) {
                map.setView([39.7392, -104.9903], 12);
                hasView = true;
            }
        }

        function render(data, renderOptions) {
            const opts = renderOptions || {};
            const points = Array.isArray(data && data.route_points)
                ? data.route_points.filter(isValidPoint)
                : [];
            const latLngs = points.map(toLatLng);
            const currentLatLng = isValidPoint(data && data.current_position)
                ? toLatLng(data.current_position)
                : null;
            const startZone = (
                isValidPoint(data && data.start_zone)
                && Number.isFinite(data.start_zone.radius_meters)
            )
                ? data.start_zone
                : null;
            const startZoneLatLng = startZone ? toLatLng(startZone) : null;
            hoverPoints = points;
            hoverEnabled = Boolean(options.enablePointHover) && points.some(hasHoverDetails);

            routeLine.setLatLngs(latLngs);

            if (startZone) {
                startZoneCircle.setLatLng(startZoneLatLng);
                startZoneCircle.setRadius(startZone.radius_meters);
                startZoneCircle.bindTooltip(
                    "Start zone (" + startZone.radius_meters.toFixed(1) + "m)",
                    { permanent: false, direction: "top" }
                );
                if (!map.hasLayer(startZoneCircle)) {
                    startZoneCircle.addTo(map);
                }
            } else {
                removeLayerIfPresent(map, startZoneCircle);
            }

            if (latLngs.length) {
                setMarker(map, startMarker, latLngs[0], "Start");
                setMarker(
                    map,
                    endMarker,
                    latLngs[latLngs.length - 1],
                    data && data.session_active ? "Latest route point" : "Finish"
                );
            } else {
                removeLayerIfPresent(map, startMarker);
                removeLayerIfPresent(map, endMarker);
            }

            if (currentLatLng) {
                setMarker(
                    map,
                    currentMarker,
                    currentLatLng,
                    data && data.session_active ? "Live position" : "Latest position"
                );
            } else {
                removeLayerIfPresent(map, currentMarker);
            }

            if (!hoverEnabled) {
                hideHoverMarker();
            }

            fitMap(latLngs, currentLatLng, startZoneLatLng, Boolean(opts.forceFit));

            if (statusElement) {
                statusElement.textContent = buildStatusText(data, latLngs.length);
            }

            window.setTimeout(function () {
                map.invalidateSize();
            }, 0);
        }

        return {
            render: render,
            recenterToRoute: function recenterToRoute(data) {
                followRoute = true;
                render(data, { forceFit: true });
            }
        };
    }
</script>
"""
RACE_LIST_TEMPLATE = """
<!doctype html>
<html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Saved Races</title>
        <style>
            :root {
                --bg: #eef3f8;
                --card: #ffffff;
                --border: #cfd9e4;
                --text: #17324d;
                --muted: #5f748a;
                --accent: #1565c0;
            }

            * {
                box-sizing: border-box;
            }

            body {
                margin: 0;
                font-family: "Segoe UI", Tahoma, sans-serif;
                background: linear-gradient(180deg, #f7fafc 0%, var(--bg) 100%);
                color: var(--text);
            }

            a {
                color: var(--accent);
            }

            .page {
                max-width: 980px;
                margin: 0 auto;
                padding: 28px 20px 40px;
            }

            .card {
                background: var(--card);
                border: 1px solid var(--border);
                border-radius: 14px;
                padding: 18px;
                box-shadow: 0 8px 24px rgba(25, 50, 75, 0.06);
            }

            .banner {
                margin: 18px 0;
                padding: 14px 16px;
                border-radius: 12px;
                border: 1px solid transparent;
            }

            .banner.error {
                background: #fee;
                border-color: #d66;
                color: #8d1b1b;
            }

            .banner.success {
                background: #eefbf3;
                border-color: #6ab184;
                color: #1a5b31;
            }

            .banner.warning {
                background: #fff6df;
                border-color: #d5a64a;
                color: #754c00;
            }

            .list {
                list-style: none;
                padding: 0;
                margin: 18px 0 0;
            }

            .list li + li {
                margin-top: 12px;
            }

            .meta {
                color: var(--muted);
                font-size: 0.95rem;
            }

            label,
            input,
            button {
                font: inherit;
            }

            input {
                margin-top: 8px;
                padding: 9px 10px;
                width: min(280px, 100%);
                border: 1px solid var(--border);
                border-radius: 8px;
            }

            button {
                margin-top: 12px;
                padding: 10px 14px;
                border-radius: 999px;
                border: 1px solid #b53a3a;
                background: #d84f4f;
                color: #fff;
                cursor: pointer;
            }
        </style>
    </head>
    <body>
        <main class="page">
            <p><a href="{{ url_for('home') }}">Back to Dashboard</a></p>
            <h1>Saved Races</h1>
            <p class="meta">Folder: <code>{{ log_folder }}</code></p>

            {% if clear_message %}
                <div class="banner {{ clear_message.kind }}">{{ clear_message.text }}</div>
            {% endif %}

            <section class="card">
                <h2 style="margin-top: 0;">Clear Past Race History</h2>
                <p>
                    This deletes saved CSV race files from <code>{{ log_folder }}</code>.
                    If a race is currently running, that active file is kept.
                </p>
                <form method="post" action="{{ url_for('clear_race_history') }}">
                    <label for="clear-history-password"><b>Password</b></label><br>
                    <input
                        id="clear-history-password"
                        type="password"
                        name="password"
                        required
                        autocomplete="current-password"
                    ><br>
                    <button
                        type="submit"
                        onclick="return confirm('Delete all past race history?');"
                    >
                        Clear All Past Race History
                    </button>
                </form>
            </section>

            <section class="card" style="margin-top: 18px;">
                <h2 style="margin-top: 0;">Race Files</h2>
                {% if race_items %}
                    <ul class="list">
                        {% for race in race_items %}
                            <li>
                                <a href="{{ url_for('view_race', filename=race.name) }}">{{ race.name }}</a><br>
                                <span class="meta">
                                    Modified: {{ race.modified_text }} |
                                    Size: {{ race.size }} bytes
                                </span>
                            </li>
                        {% endfor %}
                    </ul>
                {% else %}
                    <p>No saved races found yet.</p>
                {% endif %}
            </section>
        </main>
    </body>
</html>
"""
RACE_DETAIL_TEMPLATE = """
<!doctype html>
<html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{{ race_file_name }}</title>
        <link
            rel="stylesheet"
            href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
            integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
            crossorigin=""
        >
        <style>
            :root {
                --bg: #eef3f8;
                --card: #ffffff;
                --border: #cfd9e4;
                --text: #17324d;
                --muted: #5f748a;
                --accent: #1565c0;
                --accent-soft: #d9ebff;
            }

            * {
                box-sizing: border-box;
            }

            body {
                margin: 0;
                font-family: "Segoe UI", Tahoma, sans-serif;
                background: linear-gradient(180deg, #f7fafc 0%, var(--bg) 100%);
                color: var(--text);
            }

            a {
                color: var(--accent);
            }

            .page {
                max-width: 1180px;
                margin: 0 auto;
                padding: 28px 20px 40px;
            }

            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 14px;
                margin: 18px 0;
            }

            .card {
                background: var(--card);
                border: 1px solid var(--border);
                border-radius: 14px;
                padding: 18px;
                box-shadow: 0 8px 24px rgba(25, 50, 75, 0.06);
            }

            .card h2,
            .card h3,
            .card p {
                margin-top: 0;
            }

            .meta {
                color: var(--muted);
            }

            .map-toolbar {
                display: flex;
                flex-wrap: wrap;
                justify-content: space-between;
                align-items: center;
                gap: 12px;
                margin-bottom: 12px;
            }

            .map-status {
                color: var(--muted);
                font-size: 0.95rem;
            }

            .map-action {
                border: 1px solid #8ab4e6;
                background: var(--accent-soft);
                color: var(--accent);
                border-radius: 999px;
                padding: 8px 14px;
                font: inherit;
                cursor: pointer;
            }

            #route-map {
                width: 100%;
                height: 420px;
                border-radius: 12px;
                overflow: hidden;
                border: 1px solid var(--border);
            }

            .table-wrap {
                overflow-x: auto;
            }

            table {
                width: 100%;
                border-collapse: collapse;
            }

            th,
            td {
                border: 1px solid #cfd9e4;
                padding: 8px;
                text-align: left;
                vertical-align: top;
            }

            th {
                background: #f2f6fb;
            }
        </style>
    </head>
    <body>
        <main class="page">
            <p><a href="{{ url_for('home') }}">Dashboard</a> | <a href="{{ url_for('race_list') }}">Saved Races</a></p>
            <h1>{{ race_file_name }}</h1>
            {% if race_date_text %}
                <p class="meta">Race Date: <b>{{ race_date_text }}</b></p>
            {% endif %}

            <section class="stats-grid">
                <article class="card">
                    <h2>Rows</h2>
                    <p>{{ rows|length }}</p>
                </article>
                <article class="card">
                    <h2>Duration</h2>
                    <p>{{ duration }} seconds</p>
                </article>
                <article class="card">
                    <h2>Final Count</h2>
                    <p>{{ final_count }}</p>
                </article>
                <article class="card">
                    <h2>Max RPM</h2>
                    <p>{{ "%.2f"|format(max_rpm) }}</p>
                </article>
                <article class="card">
                    <h2>Route Points</h2>
                    <p>{{ route_point_count }}</p>
                </article>
            </section>

             <section class="card" style="margin-bottom: 18px;">
                 <div class="map-toolbar">
                     <div>
                         <h2 style="margin: 0 0 6px;">Route Map</h2>
                         <div class="map-status" id="route-map-status">Waiting for GPS route data.</div>
                     </div>
                     <button class="map-action" id="recenter-route" type="button">Recenter Route</button>
                 </div>
                 <div id="route-map"></div>
                 <p class="meta" style="margin: 12px 0 0;">Hover over the route to inspect the nearest recorded RPM and elapsed time.</p>
             </section>

            <section class="card">
                <h2>Race Data</h2>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                {% for column in fieldnames %}
                                    <th>{{ header_labels.get(column, column) }}</th>
                                {% endfor %}
                            </tr>
                        </thead>
                        <tbody>
                            {% if display_rows %}
                                {% for row in display_rows %}
                                    <tr>
                                        {% for column in fieldnames %}
                                            <td>{{ row.get(column, "") }}</td>
                                        {% endfor %}
                                    </tr>
                                {% endfor %}
                            {% else %}
                                <tr>
                                    <td colspan="{{ table_column_count }}">This race file has no data rows yet.</td>
                                </tr>
                            {% endif %}
                        </tbody>
                    </table>
                </div>
            </section>
        </main>

        <script
            src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
            integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
            crossorigin=""
        ></script>
        {{ route_map_script|safe }}
        <script>
            const routeData = {
                session_active: false,
                gps_has_fix: {{ (route_point_count > 0)|tojson }},
                current_position: {{ (route_points[-1] if route_points else none)|tojson }},
                route_points: {{ route_points|tojson }}
            };

             const routeMap = createRouteMap({
                 containerId: "route-map",
                 statusId: "route-map-status",
                 pointsLabel: "saved route points",
                 enablePointHover: true
             });

            routeMap.render(routeData, { forceFit: true });

            document.getElementById("recenter-route").addEventListener("click", function () {
                routeMap.recenterToRoute(routeData);
            });
        </script>
    </body>
</html>
"""


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


def _current_position(state):
    if not state.gps_has_fix or state.gps_latitude is None or state.gps_longitude is None:
        return None

    return {
        "latitude": round(state.gps_latitude, 6),
        "longitude": round(state.gps_longitude, 6),
    }


def _start_zone_payload(state):
    if not has_start_zone(state):
        return None

    return {
        "latitude": round(state.start_zone_latitude, 6),
        "longitude": round(state.start_zone_longitude, 6),
        "radius_meters": round(state.start_zone_radius_meters, 1),
    }


def _start_zone_status_text(state):
    if not has_start_zone(state):
        return "Not set"

    if not state.gps_has_fix or state.gps_latitude is None or state.gps_longitude is None:
        return "Set. Waiting for GPS fix."

    if not state.session_active:
        return "Ready. Inside zone." if state.start_zone_inside else "Ready. Outside zone."

    if not state.start_zone_departed:
        return (
            "Inside start zone. Leave the circle to arm lap detection."
            if state.start_zone_inside
            else "Outside start zone. Lap detection is arming."
        )

    if state.start_zone_anchor_monotonic is None:
        return "Armed. Re-enter the circle to count a lap."

    remaining_seconds = max(
        0.0,
        state.minimum_lap_seconds - (time.monotonic() - state.start_zone_anchor_monotonic),
    )
    if remaining_seconds > 0:
        return f"Outside start zone. Next lap available in {remaining_seconds:.0f}s."

    return "Armed. Re-enter the circle to count a lap."


def _live_state_payload(state):
    started_text = (
        state.session_started_at.strftime("%Y-%m-%d %H:%M:%S")
        if state.session_started_at
        else "None"
    )
    elapsed_text = f"{state.session_elapsed_seconds:.1f}s" if state.session_active else "0.0s"
    current_position = _current_position(state)
    gps_latitude_text = f"{state.gps_latitude:.6f}" if state.gps_latitude is not None else "Unknown"
    gps_longitude_text = f"{state.gps_longitude:.6f}" if state.gps_longitude is not None else "Unknown"
    gps_status_text = (
        f"FIX ({state.gps_satellites} satellites)"
        if current_position
        else "Searching for fix"
    )
    gps_maps_url = (
        f"https://www.google.com/maps?q={current_position['latitude']:.6f},{current_position['longitude']:.6f}"
        if current_position
        else None
    )
    gps_time_text = (
        f"{state.gps_utc_date} {state.gps_utc_time} UTC"
        if state.gps_utc_date and state.gps_utc_time
        else "Unknown"
    )
    start_zone = _start_zone_payload(state)
    start_zone_center_text = (
        f"{start_zone['latitude']:.6f}, {start_zone['longitude']:.6f}"
        if start_zone
        else "None"
    )
    start_zone_radius_text = f"{state.start_zone_radius_meters:.1f} m"
    minimum_lap_text = f"{state.minimum_lap_seconds:.0f} s"
    last_lap_text = (
        f"{state.last_lap_elapsed_seconds:.1f}s from start"
        if state.last_lap_elapsed_seconds is not None
        else "None"
    )

    return {
        "status": state.status,
        "session_text": "RUNNING" if state.session_active else "IDLE",
        "current_session_name": state.current_session_name,
        "last_session_name": state.last_session_name,
        "started_text": started_text,
        "elapsed_text": elapsed_text,
        "rpm_text": f"{state.rpm:.2f}",
        "count_text": str(state.count),
        "lap_count_text": str(state.lap_count),
        "last_lap_text": last_lap_text,
        "gps_has_fix": current_position is not None,
        "gps_latitude": current_position["latitude"] if current_position else None,
        "gps_longitude": current_position["longitude"] if current_position else None,
        "gps_status_text": gps_status_text,
        "gps_latitude_text": gps_latitude_text,
        "gps_longitude_text": gps_longitude_text,
        "gps_maps_url": gps_maps_url,
        "gps_time_text": gps_time_text,
        "start_zone_active": start_zone is not None,
        "start_zone_center_text": start_zone_center_text,
        "start_zone_radius_text": start_zone_radius_text,
        "start_zone_radius_value": round(state.start_zone_radius_meters, 1),
        "minimum_lap_text": minimum_lap_text,
        "minimum_lap_seconds_value": round(state.minimum_lap_seconds, 1),
        "start_zone_status_text": _start_zone_status_text(state),
        "last_raw_gps_line": state.last_raw_gps_line,
        "last_raw_gpstime_line": state.last_raw_gpstime_line,
    }


def _live_route_payload(state):
    current_position = _current_position(state)
    return {
        "session_active": state.session_active,
        "gps_has_fix": current_position is not None,
        "current_position": current_position,
        "start_zone": _start_zone_payload(state),
        "route_points": [dict(point) for point in state.live_route_points],
    }


def _dashboard_update_payload(state):
    return {
        "live_state": _attach_session_urls(_live_state_payload(state)),
        "route_state": _live_route_payload(state),
    }


def _attach_session_urls(payload):
    payload["current_session_url"] = (
        url_for("view_race", filename=payload["current_session_name"])
        if payload["current_session_name"]
        else None
    )
    payload["last_session_url"] = (
        url_for("view_race", filename=payload["last_session_name"])
        if payload["last_session_name"]
        else None
    )
    return payload


def _prepare_race_table(rows, fieldnames):
    display_rows = [dict(row) for row in rows]
    header_labels = {column: column for column in fieldnames}
    race_date_text = None

    if "timestamp" not in fieldnames or not display_rows:
        return display_rows, header_labels, race_date_text

    parsed_timestamps = []
    for row in display_rows:
        timestamp_text = row.get("timestamp", "")
        try:
            parsed_timestamps.append(datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M:%S"))
        except (TypeError, ValueError):
            return display_rows, header_labels, race_date_text

    unique_dates = {parsed.date() for parsed in parsed_timestamps}
    if len(unique_dates) != 1:
        return display_rows, header_labels, race_date_text

    race_date_text = parsed_timestamps[0].strftime("%Y-%m-%d")
    header_labels["timestamp"] = "time"

    for row, parsed in zip(display_rows, parsed_timestamps):
        row["timestamp"] = parsed.strftime("%H:%M:%S")

    return display_rows, header_labels, race_date_text


def _visible_fieldnames(fieldnames):
    return [column for column in fieldnames if column not in HIDDEN_RACE_COLUMNS]


def _extract_route_points(rows):
    route_points = []

    for row in rows:
        latitude_text = str(row.get("latitude", "") or "").strip()
        longitude_text = str(row.get("longitude", "") or "").strip()
        if not latitude_text or not longitude_text:
            continue

        try:
            point = {
                "latitude": round(float(latitude_text), 6),
                "longitude": round(float(longitude_text), 6),
            }
        except ValueError:
            continue

        elapsed_text = str(row.get("elapsed_seconds", "") or "").strip()
        if elapsed_text:
            try:
                point["elapsed_seconds"] = round(float(elapsed_text), 3)
            except ValueError:
                pass

        rpm_text = str(row.get("rpm", "") or "").strip()
        if rpm_text:
            try:
                point["rpm"] = round(float(rpm_text), 2)
            except ValueError:
                pass

        count_text = str(row.get("count", "") or "").strip()
        if count_text:
            try:
                point["count"] = int(count_text)
            except ValueError:
                pass

        timestamp_text = str(row.get("timestamp", "") or "").strip()
        if timestamp_text:
            point["timestamp"] = timestamp_text

        if (
            route_points
            and route_points[-1]["latitude"] == point["latitude"]
            and route_points[-1]["longitude"] == point["longitude"]
        ):
            route_points[-1].update(
                {
                    key: value
                    for key, value in point.items()
                    if key not in {"latitude", "longitude"}
                }
            )
            continue

        route_points.append(point)

    return route_points


def _clear_past_race_history(state):
    active_race_name = state.current_session_name if state.session_active else None
    deleted_count = 0
    skipped_active = False
    error_count = 0

    for race_file in _list_race_files():
        if active_race_name and race_file.name == active_race_name:
            skipped_active = True
            continue

        try:
            race_file.unlink()
            deleted_count += 1
        except OSError:
            error_count += 1

    if state.last_session_name and not (LOG_FOLDER / state.last_session_name).exists():
        state.last_session_name = None
        state.last_session_filename = None

    return deleted_count, skipped_active, error_count


def create_app(state):
    app = Flask(__name__)

    @app.route("/")
    def home():
        payload = _attach_session_urls(_live_state_payload(state))
        route_payload = _live_route_payload(state)
        return render_template_string(
            HOME_TEMPLATE,
            live_state=payload,
            route_map_script=ROUTE_MAP_SCRIPT,
            route_state=route_payload,
        )

    @app.route("/api/live")
    def live_state():
        payload = _attach_session_urls(_live_state_payload(state))
        response = jsonify(payload)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/api/live-route")
    def live_route():
        response = jsonify(_live_route_payload(state))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/start-zone")
    def set_start_zone():
        payload = request.get_json(silent=True) or {}
        current_position = _current_position(state)
        if current_position is None:
            return jsonify({"error": "A current GPS fix is required to set the start zone."}), 400

        try:
            radius_meters = float(payload.get("radius_meters", state.start_zone_radius_meters))
            minimum_lap_seconds = float(
                payload.get("minimum_lap_seconds", state.minimum_lap_seconds)
            )
        except (TypeError, ValueError):
            return jsonify({"error": "Radius and minimum lap time must be numbers."}), 400

        if radius_meters <= 0 or minimum_lap_seconds <= 0:
            return jsonify({"error": "Radius and minimum lap time must be positive."}), 400

        configure_start_zone(
            state,
            current_position["latitude"],
            current_position["longitude"],
            radius_meters,
            minimum_lap_seconds,
            now_monotonic=time.monotonic(),
        )
        response = jsonify(_dashboard_update_payload(state))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/start-zone/clear")
    def clear_start_zone_route():
        clear_start_zone(state)
        response = jsonify(_dashboard_update_payload(state))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/races")
    def race_list():
        race_files = _list_race_files()
        clear_status = request.args.get("clear_status")
        deleted_count = request.args.get("deleted_count", "0")
        error_count = request.args.get("error_count", "0")
        skipped_active = request.args.get("skipped_active") == "1"

        clear_message = None
        if clear_status == "bad_password":
            clear_message = {
                "kind": "error",
                "text": "Incorrect password. Race history was not deleted.",
            }
        elif clear_status == "cleared":
            message = f"Deleted {deleted_count} saved race file(s)."
            if skipped_active:
                message += " The active race file was kept."
            clear_message = {"kind": "success", "text": message}
        elif clear_status == "partial":
            message = (
                f"Deleted {deleted_count} saved race file(s), but {error_count} file(s) "
                "could not be removed."
            )
            if skipped_active:
                message += " The active race file was kept."
            clear_message = {"kind": "warning", "text": message}

        race_items = []
        for race_file in race_files:
            race_stat = race_file.stat()
            race_items.append(
                {
                    "name": race_file.name,
                    "modified_text": datetime.fromtimestamp(race_stat.st_mtime).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "size": race_stat.st_size,
                }
            )

        return render_template_string(
            RACE_LIST_TEMPLATE,
            clear_message=clear_message,
            log_folder=str(LOG_FOLDER),
            race_items=race_items,
        )

    @app.post("/races/clear-history")
    def clear_race_history():
        password = request.form.get("password", "")
        if password != CLEAR_HISTORY_PASSWORD:
            return redirect(url_for("race_list", clear_status="bad_password"))

        deleted_count, skipped_active, error_count = _clear_past_race_history(state)
        clear_status = "partial" if error_count else "cleared"
        return redirect(
            url_for(
                "race_list",
                clear_status=clear_status,
                deleted_count=deleted_count,
                error_count=error_count,
                skipped_active="1" if skipped_active else "0",
            )
        )

    @app.route("/races/<filename>")
    def view_race(filename):
        race_file = _resolve_race_file(filename)

        with race_file.open("r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            rows = list(reader)
            raw_fieldnames = reader.fieldnames or [
                "timestamp",
                "elapsed_seconds",
                "count",
                "rpm",
                "lap_count",
                "latitude",
                "longitude",
                "gps_fix",
                "gps_satellites",
                "gps_utc_date",
                "gps_utc_time",
            ]

        fieldnames = _visible_fieldnames(raw_fieldnames) or raw_fieldnames
        max_rpm = 0.0
        final_count = 0
        duration = "0.00"
        display_rows, header_labels, race_date_text = _prepare_race_table(rows, fieldnames)
        route_points = _extract_route_points(rows)

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

        return render_template_string(
            RACE_DETAIL_TEMPLATE,
            display_rows=display_rows,
            duration=duration,
            fieldnames=fieldnames,
            final_count=final_count,
            header_labels=header_labels,
            max_rpm=max_rpm,
            race_date_text=race_date_text,
            race_file_name=race_file.name,
            route_map_script=ROUTE_MAP_SCRIPT,
            route_points=route_points,
            route_point_count=len(route_points),
            rows=rows,
            table_column_count=max(len(fieldnames), 1),
        )

    return app
