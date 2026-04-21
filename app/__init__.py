import logging
import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")

    db.init_app(app)

    from app.routes import main

    app.register_blueprint(main)

    with app.app_context():
        db.create_all()

    _start_scheduler(app)

    return app


def _start_scheduler(app):
    quick_minutes = app.config.get("AUTO_SCAN_MINUTES", 0)
    deep_hours = app.config.get("DEEP_SCAN_HOURS", 0)
    if quick_minutes <= 0 and deep_hours <= 0:
        return

    # Avoid running twice under Flask's reloader
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    from apscheduler.schedulers.background import BackgroundScheduler

    from app.scanner import deep_scan, quick_scan

    def quick_job():
        with app.app_context():
            try:
                quick_scan(app.config["NETWORK_CIDR"])
            except Exception as e:
                logger.error("Auto quick scan failed: %s", e)

    def deep_job():
        with app.app_context():
            try:
                deep_scan(app.config["NETWORK_CIDR"])
            except Exception as e:
                logger.error("Auto deep scan failed: %s", e)

    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")

    if quick_minutes > 0:
        scheduler.add_job(
            quick_job, "interval", minutes=quick_minutes,
            id="auto-quick-scan", max_instances=1, coalesce=True,
        )
        logger.info("Auto quick scan scheduled every %d minutes", quick_minutes)

    if deep_hours > 0:
        scheduler.add_job(
            deep_job, "interval", hours=deep_hours,
            id="auto-deep-scan", max_instances=1, coalesce=True,
        )
        logger.info("Auto deep scan scheduled every %d hours", deep_hours)

    scheduler.start()
