from datetime import datetime, timezone

from app import db


class Device(db.Model):
    """A device discovered on the network, identified by MAC address."""

    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    mac_address = db.Column(db.String(17), unique=True, nullable=False, index=True)
    ip_address = db.Column(db.String(45))
    hostname = db.Column(db.String(255))
    custom_name = db.Column(db.String(255))
    vendor = db.Column(db.String(255))
    os_info = db.Column(db.String(255))
    open_ports = db.Column(db.Text)  # JSON string
    first_seen = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    last_seen = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    is_online = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)

    scans = db.relationship("ScanRecord", backref="device", lazy="dynamic")

    def display_name(self):
        return self.custom_name or self.hostname or self.ip_address

    def to_dict(self):
        return {
            "id": self.id,
            "mac_address": self.mac_address,
            "ip_address": self.ip_address,
            "hostname": self.hostname,
            "custom_name": self.custom_name,
            "display_name": self.display_name(),
            "vendor": self.vendor,
            "os_info": self.os_info,
            "open_ports": self.open_ports,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "is_online": self.is_online,
            "notes": self.notes,
        }


class ScanRecord(db.Model):
    """Historical record of each time a device was seen during a scan."""

    __tablename__ = "scan_records"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=False)
    ip_address = db.Column(db.String(45))
    scan_time = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    scan_type = db.Column(db.String(50))  # "quick", "deep"

    def to_dict(self):
        return {
            "id": self.id,
            "device_id": self.device_id,
            "ip_address": self.ip_address,
            "scan_time": self.scan_time.isoformat() if self.scan_time else None,
            "scan_type": self.scan_type,
        }
