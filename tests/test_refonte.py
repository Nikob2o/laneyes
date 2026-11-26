"""Refonte du 26/11/2026 : vue d'ensemble, filtres, fiche, archivage, journal."""
import re
import sqlite3
from datetime import timedelta
from pathlib import Path

from conftest import maintenant

STATIQUE = Path(__file__).resolve().parent.parent / "app" / "static"


def _evenement(app, type_="quick", statut="success", hotes=10, il_y_a_jours=0, duree=4700):
    from app import db
    from app.models import ScanEvent
    with app.app_context():
        debut = maintenant() - timedelta(days=il_y_a_jours)
        db.session.add(ScanEvent(scan_type=type_, target="10.9.8.0/24", status=statut, hosts_found=hotes,
                                 new_devices=0, started_at=debut, finished_at=debut, duration_ms=duree))
        db.session.commit()


def test_migration_ajoute_archived_sans_perdre_les_donnees(tmp_path, monkeypatch):
    """Une base d'avant la refonte (sans colonne archived) est migrée au démarrage."""
    chemin = tmp_path / "ancienne.db"
    con = sqlite3.connect(chemin)
    con.executescript("""
        CREATE TABLE devices (id INTEGER PRIMARY KEY, mac_address VARCHAR(17) UNIQUE NOT NULL,
            ip_address VARCHAR(45), hostname VARCHAR(255), custom_name VARCHAR(255), vendor VARCHAR(255),
            os_info VARCHAR(255), open_ports TEXT, first_seen DATETIME, last_seen DATETIME,
            is_online BOOLEAN, notes TEXT);
        INSERT INTO devices (mac_address, ip_address, custom_name, is_online, first_seen, last_seen)
            VALUES ('aa:bb:cc:00:00:01', '10.9.8.2', 'Box', 1, '2026-11-01 10:00:00', '2026-11-26 10:00:00');
    """)
    con.commit()
    con.close()
    from config import Config
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{chemin}")
    from app import create_app
    app = create_app()
    colonnes = {r[1] for r in sqlite3.connect(chemin).execute("PRAGMA table_info(devices)")}
    assert {"archived", "archived_at"} <= colonnes
    r = app.test_client().get("/api/devices").get_json()
    assert [d["custom_name"] for d in r] == ["Box"] and r[0]["archived"] is False
    create_app()  # idempotent : une seconde migration ne casse rien


def test_vue_d_ensemble_sans_camemberts(client, app, ajouter):
    ajouter("aa:00:00:00:00:01", "10.9.8.1", nom="Box")
    ajouter("aa:00:00:00:00:02", "10.9.8.2", apparu_il_y_a=2)                       # nouveau, sans nom
    ajouter("aa:00:00:00:00:03", "10.9.8.3", en_ligne=False, vu_il_y_a=20)          # fantôme
    ajouter("aa:00:00:00:00:04", "10.9.8.4", en_ligne=False, vu_il_y_a=2, nom="TV")  # hors ligne récent
    _evenement(app, hotes=2, il_y_a_jours=3)
    _evenement(app, hotes=3)
    _evenement(app, statut="failed", hotes=0)
    d = client.get("/api/dashboard").get_json()
    s = d["stats"]
    assert (s["online"], s["total_devices"], s["new_this_week"], s["unnamed"], s["ghosts"]) == (2, 4, 1, 2, 1)
    assert "vendors" not in d and "os_families" not in d
    assert len(d["timeline"]) == 7 and d["timeline"][-1]["hosts"] == 3   # l'échec ne fait pas baisser la courbe
    assert d["timeline"][-4]["hosts"] == 2 and d["timeline"][0]["hosts"] is None
    assert [x["ip_address"] for x in d["new_devices"]] == ["10.9.8.2"]
    assert {x["ip_address"] for x in d["online_devices"]} == {"10.9.8.1", "10.9.8.2"}
    assert s["last_scan"]["status"] == "failed"


def test_filtres_des_appareils(client, ajouter):
    ajouter("aa:00:00:00:00:01", "10.9.8.1", nom="Box")
    ajouter("aa:00:00:00:00:02", "10.9.8.2", hostname="esp32-7f21")
    ajouter("aa:00:00:00:00:03", "10.9.8.3", en_ligne=False, vu_il_y_a=3)

    def ips(url):
        return {d["ip_address"] for d in client.get(url).get_json()}
    assert ips("/api/devices?status=online") == {"10.9.8.1", "10.9.8.2"}
    assert ips("/api/devices?status=offline") == {"10.9.8.3"}
    assert ips("/api/devices?a_identifier=1") == {"10.9.8.2", "10.9.8.3"}
    assert ips("/api/devices?status=online&a_identifier=1") == {"10.9.8.2"}
    assert ips("/api/devices?q=esp32") == {"10.9.8.2"}
    assert ips("/api/devices?q=00:00:03") == {"10.9.8.3"}
    assert ips("/api/devices?q=box") == {"10.9.8.1"}
    c = client.get("/api/devices/counts").get_json()
    assert (c["total"], c["online"], c["offline"], c["a_identifier"]) == (3, 2, 1, 2)


def test_renommer_sur_place(client, ajouter):
    i = ajouter("aa:00:00:00:00:02", "10.9.8.2")
    r = client.put(f"/api/devices/{i}", json={"custom_name": "  Radio ICOM  "})
    assert r.get_json()["custom_name"] == "Radio ICOM"
    assert client.put(f"/api/devices/{i}", json={"custom_name": ""}).get_json()["custom_name"] is None


def test_archiver_masque_sans_supprimer_et_revient_si_revu(client, app, ajouter):
    i = ajouter("aa:00:00:00:00:02", "10.9.8.2", en_ligne=False, vu_il_y_a=10)
    assert client.post(f"/api/devices/{i}/archive").get_json()["archived"] is True
    assert client.get("/api/devices").get_json() == []
    assert client.get("/api/devices/counts").get_json()["total"] == 0
    assert [d["id"] for d in client.get("/api/devices?archives=1").get_json()] == [i]
    assert client.get(f"/api/devices/{i}").status_code == 200   # toujours en base
    # Le scanner le revoit (last_seen avance) : il réapparaît sans qu'on touche au scanner.
    from app import db
    from app.models import Device
    with app.app_context():
        d = db.session.get(Device, i)
        d.last_seen, d.is_online = maintenant() + timedelta(seconds=1), True
        db.session.commit()
    assert [d["id"] for d in client.get("/api/devices").get_json()] == [i]
    assert client.post(f"/api/devices/{i}/unarchive").get_json()["archived"] is False


def test_archiver_les_fantomes_demande_confirmation(client, ajouter):
    ajouter("aa:00:00:00:00:01", "10.9.8.1", nom="Box")
    ajouter("aa:00:00:00:00:02", "10.9.8.2", en_ligne=False, vu_il_y_a=8)
    ajouter("aa:00:00:00:00:03", "10.9.8.3", en_ligne=False, vu_il_y_a=30)
    ajouter("aa:00:00:00:00:04", "10.9.8.4", en_ligne=False, vu_il_y_a=6)   # pas encore fantôme
    r = client.post("/api/devices/archive-ghosts", json={})
    assert r.status_code == 400 and r.get_json() == {"archived": 0, "would_archive": 2}
    assert client.get("/api/devices/counts").get_json()["total"] == 4
    assert client.post("/api/devices/archive-ghosts", json={"confirm": True}).get_json() == {"archived": 2}
    assert {d["ip_address"] for d in client.get("/api/devices").get_json()} == {"10.9.8.1", "10.9.8.4"}
    assert client.get("/api/devices/counts").get_json()["fantomes"] == 0


def test_presence_sur_14_jours(client, ajouter):
    i = ajouter("aa:00:00:00:00:02", "10.9.8.2", jours_vus=(0, 0, 1, 5, 20))
    p = client.get(f"/api/devices/{i}/presence?days=14").get_json()
    assert len(p) == 14
    presents = [j["date"] for j in p if j["present"]]
    # Vu aujourd'hui (deux fois), hier et il y a 5 jours ; le passage d'il y a 20 jours est hors fenêtre.
    assert len(presents) == 3 and p[-1]["present"] and p[-2]["present"] and p[-6]["present"]


def test_journal_filtres(client, app):
    _evenement(app, "quick")
    _evenement(app, "deep", duree=192000)
    _evenement(app, "quick", statut="failed")

    def types(url):
        return [e["scan_type"] + "/" + e["status"] for e in client.get(url).get_json()]
    assert len(types("/api/events")) == 3
    assert set(types("/api/events?type=quick")) == {"quick/success", "quick/failed"}
    assert types("/api/events?type=deep") == ["deep/success"]
    assert types("/api/events?status=failed") == ["quick/failed"]


def test_page_en_francais_sans_violet_ni_emoji_ni_chartjs(client):
    page = client.get("/").get_data(as_text=True)
    for texte in ("Vue d'ensemble", "Appareils", "À identifier", "Journal des scans", "Réseau surveillé",
                  "10.9.8.0/24", "Archiver les fantômes ?", "Présence, 14 derniers jours"):
        assert texte in page, texte
    for interdit in ("Quick Scan", "Dashboard", "Devices", "chart.js", "Chart("):
        assert interdit not in page, interdit
    tout = page + "".join((STATIQUE / f).read_text() for f in ("app.js", "style.css", "logo.svg"))
    assert "6c5ce7" not in tout.lower() and "7d6ff0" not in tout.lower()
    emojis = re.findall(r"[\U0001F300-\U0001FAFF☀-➿]|&#(?:9[0-9]{3}|1[0-9]{5});", tout)
    assert emojis == []
    # L'interface n'efface jamais un appareil : elle archive.
    assert 'method: "DELETE"' not in (STATIQUE / "app.js").read_text()
