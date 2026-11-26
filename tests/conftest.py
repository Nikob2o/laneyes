"""Tests de l'interface et de l'API de Laneyes : base SQLite jetable, aucun scan réel."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

# Avant tout import de config : pas de planificateur ni de purge pendant les tests.
os.environ["AUTO_SCAN_MINUTES"] = "0"
os.environ["DEEP_SCAN_HOURS"] = "0"
os.environ["SCAN_RECORD_RETENTION_DAYS"] = "0"
os.environ.setdefault("NETWORK_CIDR", "10.9.8.0/24")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def maintenant():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def app(tmp_path, monkeypatch):
    from config import Config
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{tmp_path / 't.db'}")
    from app import create_app
    application = create_app()
    application.config["TESTING"] = True
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def ajouter(app):
    """ajouter(mac, ip, en_ligne=True, nom=None, vu_il_y_a=0 (jours), apparu_il_y_a=30, jours_vus=())"""
    from app import db
    from app.models import Device, ScanRecord

    def _ajouter(mac, ip, en_ligne=True, nom=None, vu_il_y_a=0, apparu_il_y_a=30, jours_vus=(), **plus):
        with app.app_context():
            t = maintenant()
            d = Device(mac_address=mac, ip_address=ip, custom_name=nom, is_online=en_ligne,
                       last_seen=t - timedelta(days=vu_il_y_a), first_seen=t - timedelta(days=apparu_il_y_a), **plus)
            db.session.add(d)
            db.session.flush()
            for j in jours_vus:
                db.session.add(ScanRecord(device_id=d.id, ip_address=ip, scan_type="quick",
                                          scan_time=t - timedelta(days=j)))
            db.session.commit()
            return d.id
    return _ajouter
