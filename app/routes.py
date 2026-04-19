from collections import Counter
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func

from app import db
from app.models import Device, ScanRecord, ScanEvent
from app.scanner import quick_scan, deep_scan
from config import Config


def _os_family(os_info: str | None) -> str:
    """Extract a simple OS family label from the nmap os_info string."""
    if not os_info:
        return "Unknown"
    s = os_info.lower()
    if "apple" in s or "mac" in s or "ios" in s or "darwin" in s:
        return "Apple"
    if "windows" in s:
        return "Windows"
    if "android" in s:
        return "Android"
    if "qnap" in s:
        return "QNAP"
    if "linux" in s or "ubuntu" in s or "debian" in s or "raspbian" in s:
        return "Linux"
    if "freebsd" in s or "openbsd" in s or "netbsd" in s:
        return "BSD"
    return "Other"

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


# --- API: Dashboard ---


@main.route("/api/dashboard")
def api_dashboard():
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Basic counts
    total = Device.query.count()
    online = Device.query.filter_by(is_online=True).count()
    offline = total - online
    online_percent = round((online / total * 100), 1) if total > 0 else 0

    new_this_week = Device.query.filter(Device.first_seen >= week_ago).count()
    unnamed = Device.query.filter(
        (Device.custom_name.is_(None)) | (Device.custom_name == "")
    ).count()

    # Last scan event
    last_event = ScanEvent.query.order_by(ScanEvent.started_at.desc()).first()
    last_scan = None
    if last_event:
        age_seconds = int((now - last_event.started_at.replace(tzinfo=timezone.utc)).total_seconds())
        last_scan = {
            "started_at": last_event.started_at.isoformat(),
            "status": last_event.status,
            "scan_type": last_event.scan_type,
            "hosts_found": last_event.hosts_found,
            "age_seconds": age_seconds,
        }

    # Timeline: hosts found per scan event over last 7 days, daily buckets
    timeline_events = (
        ScanEvent.query
        .filter(ScanEvent.started_at >= week_ago)
        .filter(ScanEvent.scan_type == "quick")
        .order_by(ScanEvent.started_at.asc())
        .all()
    )
    daily_buckets = {}
    for ev in timeline_events:
        day = ev.started_at.replace(hour=0, minute=0, second=0, microsecond=0)
        key = day.date().isoformat()
        # Keep the max hosts_found observed that day
        if key not in daily_buckets or ev.hosts_found > daily_buckets[key]:
            daily_buckets[key] = ev.hosts_found
    timeline = [{"date": k, "hosts": v} for k, v in sorted(daily_buckets.items())]

    # Top vendors
    vendor_counts = Counter()
    for dev in Device.query.filter(Device.vendor.isnot(None)).all():
        vendor_counts[dev.vendor] += 1
    vendors = [{"name": n, "count": c} for n, c in vendor_counts.most_common(6)]

    # OS families
    os_counts = Counter()
    for dev in Device.query.all():
        os_counts[_os_family(dev.os_info)] += 1
    os_families = [{"name": n, "count": c} for n, c in os_counts.most_common()]

    # Recent events (last 5)
    recent_events = (
        ScanEvent.query.order_by(ScanEvent.started_at.desc()).limit(5).all()
    )

    # New devices (last 7 days, max 5)
    new_devices = (
        Device.query.filter(Device.first_seen >= week_ago)
        .order_by(Device.first_seen.desc())
        .limit(5)
        .all()
    )

    # Ghost devices (offline, last seen >7 days ago, max 5)
    ghost_devices = (
        Device.query.filter(Device.is_online.is_(False))
        .filter(Device.last_seen < week_ago)
        .order_by(Device.last_seen.desc())
        .limit(5)
        .all()
    )

    return jsonify({
        "stats": {
            "total_devices": total,
            "online": online,
            "offline": offline,
            "online_percent": online_percent,
            "new_this_week": new_this_week,
            "unnamed": unnamed,
            "last_scan": last_scan,
        },
        "timeline": timeline,
        "vendors": vendors,
        "os_families": os_families,
        "recent_events": [e.to_dict() for e in recent_events],
        "new_devices": [d.to_dict() for d in new_devices],
        "ghost_devices": [d.to_dict() for d in ghost_devices],
    })


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
