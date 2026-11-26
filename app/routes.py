from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import and_, or_

from app import db
from app.models import Device, ScanRecord, ScanEvent
from app.scanner import quick_scan, deep_scan
from config import Config

main = Blueprint("main", __name__)

# Un appareil hors ligne depuis plus longtemps que ça est un « fantôme ».
JOURS_FANTOME = 7


def _maintenant() -> datetime:
    """UTC sans fuseau : c'est ainsi que SQLite rend les dates stockées par le scanner."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _visible():
    """Les appareils affichés : non archivés, ou archivés puis revus sur le réseau."""
    return or_(
        Device.archived.is_(False),
        and_(Device.archived_at.isnot(None), Device.last_seen > Device.archived_at),
    )


def _sans_nom():
    return or_(Device.custom_name.is_(None), Device.custom_name == "")


def _fantomes(maintenant: datetime):
    limite = maintenant - timedelta(days=JOURS_FANTOME)
    return Device.query.filter(_visible(), Device.is_online.is_(False), Device.last_seen < limite)


@main.route("/")
def index():
    return render_template(
        "index.html",
        reseau=Config.NETWORK_CIDR,
        cadence_rapide=Config.AUTO_SCAN_MINUTES,
        cadence_approfondi=Config.DEEP_SCAN_HOURS,
    )


# --- API : scans ---


@main.route("/api/scan/quick", methods=["POST"])
def api_quick_scan():
    data = request.get_json(silent=True) or {}
    network = data.get("network", Config.NETWORK_CIDR)
    result = quick_scan(network)
    return jsonify(result)


@main.route("/api/scan/deep", methods=["POST"])
def api_deep_scan():
    data = request.get_json(silent=True) or {}
    target_ip = data.get("target_ip")
    network = data.get("network", Config.NETWORK_CIDR)
    result = deep_scan(network, target_ip)
    return jsonify(result)


# --- API : appareils ---


@main.route("/api/devices")
def api_devices():
    """Liste des appareils visibles.

    status : online | offline | (rien = tous) ; a_identifier=1 : sans nom donné ;
    q : nom, nom d'hôte, IP ou MAC ; archives=1 : les archivés seulement.
    """
    status = request.args.get("status")
    query = Device.query
    if request.args.get("archives") == "1":
        query = query.filter(~_visible())
    else:
        query = query.filter(_visible())
    if status == "online":
        query = query.filter(Device.is_online.is_(True))
    elif status == "offline":
        query = query.filter(Device.is_online.is_(False))
    if request.args.get("a_identifier") == "1":
        query = query.filter(_sans_nom())
    q = (request.args.get("q") or "").strip()
    if q:
        motif = f"%{q}%"
        query = query.filter(or_(
            Device.custom_name.ilike(motif), Device.hostname.ilike(motif),
            Device.ip_address.ilike(motif), Device.mac_address.ilike(motif),
            Device.vendor.ilike(motif),
        ))
    devices = query.order_by(Device.is_online.desc(), Device.last_seen.desc()).all()
    return jsonify([d.to_dict() for d in devices])


@main.route("/api/devices/counts")
def api_device_counts():
    """Compteurs de la barre latérale et des filtres."""
    visibles = Device.query.filter(_visible())
    return jsonify({
        "total": visibles.count(),
        "online": visibles.filter(Device.is_online.is_(True)).count(),
        "offline": visibles.filter(Device.is_online.is_(False)).count(),
        "a_identifier": visibles.filter(_sans_nom()).count(),
        "fantomes": _fantomes(_maintenant()).count(),
    })


@main.route("/api/devices/<int:device_id>")
def api_device_detail(device_id):
    device = db.get_or_404(Device, device_id)
    return jsonify(device.to_dict())


@main.route("/api/devices/<int:device_id>", methods=["PUT"])
def api_update_device(device_id):
    device = db.get_or_404(Device, device_id)
    data = request.get_json()

    if "custom_name" in data:
        device.custom_name = (data["custom_name"] or "").strip() or None
    if "notes" in data:
        device.notes = data["notes"] or None

    db.session.commit()
    return jsonify(device.to_dict())


@main.route("/api/devices/<int:device_id>", methods=["DELETE"])
def api_delete_device(device_id):
    device = db.get_or_404(Device, device_id)
    ScanRecord.query.filter_by(device_id=device.id).delete()
    db.session.delete(device)
    db.session.commit()
    return jsonify({"status": "deleted"})


@main.route("/api/devices/<int:device_id>/archive", methods=["POST"])
def api_archive_device(device_id):
    device = db.get_or_404(Device, device_id)
    device.archived = True
    device.archived_at = _maintenant()
    db.session.commit()
    return jsonify(device.to_dict())


@main.route("/api/devices/<int:device_id>/unarchive", methods=["POST"])
def api_unarchive_device(device_id):
    device = db.get_or_404(Device, device_id)
    device.archived = False
    device.archived_at = None
    db.session.commit()
    return jsonify(device.to_dict())


@main.route("/api/devices/archive-ghosts", methods=["POST"])
def api_archive_ghosts():
    """Archive en une fois les appareils hors ligne depuis plus de 7 jours.
    Sans {"confirm": true}, ne fait rien et dit combien seraient archivés."""
    maintenant = _maintenant()
    fantomes = _fantomes(maintenant).all()
    data = request.get_json(silent=True) or {}
    if data.get("confirm") is not True:
        return jsonify({"archived": 0, "would_archive": len(fantomes)}), 400
    for device in fantomes:
        device.archived = True
        device.archived_at = maintenant
    db.session.commit()
    return jsonify({"archived": len(fantomes)})


@main.route("/api/devices/<int:device_id>/presence")
def api_device_presence(device_id):
    """Présence jour par jour (UTC) sur les N derniers jours, d'après scan_records."""
    db.get_or_404(Device, device_id)
    jours = max(1, min(request.args.get("days", 14, type=int), 30))
    aujourd_hui = _maintenant().date()
    debut = aujourd_hui - timedelta(days=jours - 1)
    vus = {
        r.scan_time.date()
        for r in ScanRecord.query.with_entities(ScanRecord.scan_time)
        .filter(ScanRecord.device_id == device_id)
        .filter(ScanRecord.scan_time >= datetime.combine(debut, datetime.min.time()))
    }
    return jsonify([
        {"date": (debut + timedelta(days=i)).isoformat(), "present": (debut + timedelta(days=i)) in vus}
        for i in range(jours)
    ])


# --- API : historique ---


@main.route("/api/devices/<int:device_id>/history")
def api_device_history(device_id):
    db.get_or_404(Device, device_id)
    records = (
        ScanRecord.query.filter_by(device_id=device_id)
        .order_by(ScanRecord.scan_time.desc())
        .limit(100)
        .all()
    )
    return jsonify([r.to_dict() for r in records])


@main.route("/api/history")
def api_global_history():
    limit = request.args.get("limit", 200, type=int)
    records = (
        ScanRecord.query.order_by(ScanRecord.scan_time.desc())
        .limit(limit)
        .all()
    )
    return jsonify([r.to_dict() for r in records])


# --- API : vue d'ensemble ---


@main.route("/api/dashboard")
def api_dashboard():
    maintenant = _maintenant()
    semaine = maintenant - timedelta(days=7)
    visibles = Device.query.filter(_visible())

    total = visibles.count()
    online = visibles.filter(Device.is_online.is_(True)).count()

    dernier = ScanEvent.query.order_by(ScanEvent.started_at.desc()).first()
    last_scan = None
    if dernier:
        last_scan = {
            "started_at": dernier.started_at.isoformat(),
            "status": dernier.status,
            "scan_type": dernier.scan_type,
            "hosts_found": dernier.hosts_found,
            "duration_ms": dernier.duration_ms,
            "age_seconds": int((maintenant - dernier.started_at.replace(tzinfo=None)).total_seconds()),
        }

    # Courbe : maximum d'hôtes vus par un scan rapide réussi, jour par jour, 7 jours.
    debut = (maintenant - timedelta(days=6)).date()
    maxima = {}
    for ev in (ScanEvent.query
               .filter(ScanEvent.scan_type == "quick", ScanEvent.status != "failed")
               .filter(ScanEvent.started_at >= datetime.combine(debut, datetime.min.time()))):
        jour = ev.started_at.date().isoformat()
        maxima[jour] = max(maxima.get(jour, 0), ev.hosts_found or 0)
    timeline = []
    for i in range(7):
        jour = (debut + timedelta(days=i)).isoformat()
        timeline.append({"date": jour, "hosts": maxima.get(jour)})

    nouveaux = (visibles.filter(Device.first_seen >= semaine)
                .order_by(Device.first_seen.desc()).limit(6).all())
    en_ligne = (visibles.filter(Device.is_online.is_(True))
                .order_by(Device.custom_name.is_(None), Device.custom_name, Device.ip_address).all())

    return jsonify({
        "stats": {
            "total_devices": total,
            "online": online,
            "offline": total - online,
            "new_this_week": visibles.filter(Device.first_seen >= semaine).count(),
            "unnamed": visibles.filter(_sans_nom()).count(),
            "ghosts": _fantomes(maintenant).count(),
            "last_scan": last_scan,
        },
        "timeline": timeline,
        "new_devices": [d.to_dict() for d in nouveaux],
        "online_devices": [d.to_dict() for d in en_ligne],
    })


# --- API : stats ---


@main.route("/api/stats")
def api_stats():
    visibles = Device.query.filter(_visible())
    total = visibles.count()
    online = visibles.filter(Device.is_online.is_(True)).count()
    return jsonify({
        "total_devices": total,
        "online": online,
        "offline": total - online,
        "total_scans": ScanRecord.query.count(),
    })


# --- API : journal des scans ---


@main.route("/api/events")
def api_events():
    scan_type = request.args.get("type")  # quick, deep
    status = request.args.get("status")  # success, failed, partial
    limit = request.args.get("limit", 200, type=int)

    query = ScanEvent.query
    if scan_type in ("quick", "deep"):
        query = query.filter_by(scan_type=scan_type)
    if status in ("success", "failed", "partial"):
        query = query.filter_by(status=status)

    events = query.order_by(ScanEvent.started_at.desc()).limit(limit).all()
    return jsonify([e.to_dict() for e in events])


@main.route("/api/events/<int:event_id>")
def api_event_detail(event_id):
    event = db.get_or_404(ScanEvent, event_id)
    return jsonify(event.to_dict())


@main.route("/api/events", methods=["DELETE"])
def api_events_clear():
    ScanEvent.query.delete()
    db.session.commit()
    return jsonify({"status": "cleared"})
