from flask import Blueprint, jsonify, render_template, request

from app import db
from app.models import Device, ScanRecord, ScanEvent
from app.scanner import quick_scan, deep_scan
from config import Config

main = Blueprint("main", __name__)


@main.route("/")
def index():
    return render_template("index.html")


# --- API: Scanning ---


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


# --- API: Devices ---


@main.route("/api/devices")
def api_devices():
    status = request.args.get("status")  # "online", "offline", or None for all
    query = Device.query
    if status == "online":
        query = query.filter_by(is_online=True)
    elif status == "offline":
        query = query.filter_by(is_online=False)
    devices = query.order_by(Device.last_seen.desc()).all()
    return jsonify([d.to_dict() for d in devices])


@main.route("/api/devices/<int:device_id>")
def api_device_detail(device_id):
    device = db.get_or_404(Device, device_id)
    return jsonify(device.to_dict())


@main.route("/api/devices/<int:device_id>", methods=["PUT"])
def api_update_device(device_id):
    device = db.get_or_404(Device, device_id)
    data = request.get_json()

    if "custom_name" in data:
        device.custom_name = data["custom_name"] or None
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


# --- API: History ---


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


# --- API: Stats ---


@main.route("/api/stats")
def api_stats():
    total = Device.query.count()
    online = Device.query.filter_by(is_online=True).count()
    offline = total - online
    scans = ScanRecord.query.count()
    return jsonify({
        "total_devices": total,
        "online": online,
        "offline": offline,
        "total_scans": scans,
    })


# --- API: Scan Events (logs) ---


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
