"""Flask app serving the Line 2 dashboard.

Run from the repository root:  python -m line2_dashboard.app
"""
import logging

from flask import Flask, jsonify, render_template, request

from . import config, db, service

app = Flask(__name__)
log = logging.getLogger(__name__)


@app.route("/")
def index():
    return render_template("index.html", line_name=config.LINE_NAME,
                           refresh_seconds=config.REFRESH_SECONDS)


@app.route("/api/line")
def api_line():
    try:
        return jsonify(service.line_snapshot())
    except Exception as exc:  # DB down, bad credentials, network, ...
        log.exception("Failed to load line snapshot")
        return jsonify({"error": f"Database error: {exc}"}), 503


@app.route("/api/events")
def api_events():
    limit = min(max(request.args.get("limit", config.EVENTS_LIMIT, type=int), 1), 500)
    try:
        return jsonify({"events": service.recent_events(limit)})
    except Exception as exc:
        log.exception("Failed to load events")
        return jsonify({"error": f"Database error: {exc}"}), 503


@app.route("/health")
def health():
    try:
        db.ping()
        return jsonify({"db": "ok", "server": f"{config.DB_HOST},{config.DB_PORT}"})
    except Exception as exc:
        return jsonify({"db": "error", "server": f"{config.DB_HOST},{config.DB_PORT}",
                        "detail": str(exc)}), 503


def main():
    logging.basicConfig(level=logging.INFO)
    app.run(host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
