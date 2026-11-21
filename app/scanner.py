import json
import os
import socket
import subprocess
import sys
import threading
import traceback
from datetime import datetime, timedelta, timezone

import nmap
from flask import current_app

from app import db
from app.models import Device, ScanRecord, ScanEvent


def _record_event(scan_type, target, started_at, status, message,
                  hosts_found=0, new_devices=0):
    """Persist a ScanEvent row and return the dict."""
    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    event = ScanEvent(
        scan_type=scan_type,
        target=target,
        status=status,
        message=message,
        hosts_found=hosts_found,
        new_devices=new_devices,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
    )
    db.session.add(event)
    db.session.commit()
    return event


# OUI prefix -> vendor table, loaded once per process.
# MacLookup() re-reads and re-parses the whole vendor file (~35k entries)
# on every instance: with one instance per host per quick scan, that was
# ~300 full reloads an hour, churning memory that never went back to the OS.
_vendor_prefixes = None
_vendor_lock = threading.Lock()


def _load_vendor_prefixes() -> dict:
    global _vendor_prefixes
    with _vendor_lock:
        if _vendor_prefixes is None:
            try:
                from mac_vendor_lookup import MacLookup
                lookup = MacLookup()
                lookup.load_vendors()
                _vendor_prefixes = lookup.async_lookup.prefixes or {}
            except Exception:
                # Retry on the next call rather than caching a failure
                return {}
        return _vendor_prefixes


def _get_mac_vendor(mac: str) -> str:
    """Resolve MAC vendor from the OUI table (loaded once)."""
    try:
        from mac_vendor_lookup import BaseMacLookup
        prefix = BaseMacLookup.sanitise(mac)[:6].encode("utf8")
        vendor = _load_vendor_prefixes().get(prefix)
        return vendor.decode("utf8") if vendor else ""
    except Exception:
        return ""


def _resolve_hostname(ip: str) -> str:
    """Reverse DNS lookup for an IP address."""
    try:
        hostname, _, _ = socket.gethostbyaddr(ip)
        return hostname
    except (socket.herror, socket.gaierror, OSError):
        return ""


def _get_local_info() -> dict | None:
    """Get the local machine's IP and MAC address."""
    try:
        output = subprocess.check_output(["ip", "-o", "link", "show"], text=True, timeout=5)
        route = subprocess.check_output(["ip", "route", "get", "1.1.1.1"], text=True, timeout=5)
        # Find the interface used for default route
        iface = None
        local_ip = None
        for part in route.split():
            if iface is None and part == "dev":
                continue
            if "dev" in route and part != "dev":
                # parse "... dev wlan0 src 192.168.1.23 ..."
                pass
        parts = route.split()
        for i, p in enumerate(parts):
            if p == "dev" and i + 1 < len(parts):
                iface = parts[i + 1]
            if p == "src" and i + 1 < len(parts):
                local_ip = parts[i + 1]

        if not iface or not local_ip:
            return None

        # Get MAC of that interface
        for line in output.splitlines():
            if iface in line and "link/ether" in line:
                idx = line.index("link/ether") + len("link/ether")
                mac = line[idx:].strip().split()[0].upper()
                return {"ip": local_ip, "mac": mac}
    except Exception:
        pass
    return None


def _discover_hosts(network_cidr: str) -> list[dict]:
    """
    Multi-method host discovery to maximize detection:
    1. nmap combined ping scan (ARP + ICMP + TCP) — catches most LAN devices
    2. ARP table — catches anything we've communicated with recently
    3. Local machine — always included
    Returns deduplicated list of {ip, mac} dicts.
    """
    seen = {}  # mac -> {ip, mac}

    # Method 1: combined ARP + ICMP + TCP probes in a single nmap invocation
    # (was previously two separate scans, which doubled RAM/CPU on small nodes)
    try:
        nm = nmap.PortScanner()
        nm.scan(hosts=network_cidr, arguments="-sn -PR -PE -PP -PA80,443 --send-eth -T4")
        for host in nm.all_hosts():
            addr = nm[host].get("addresses", {})
            ip = addr.get("ipv4", host)
            mac = addr.get("mac", "").upper()
            if mac and mac not in seen:
                seen[mac] = {"ip": ip, "mac": mac}
    except Exception:
        pass

    # Method 2: Parse ARP table (catches anything from recent traffic)
    try:
        output = subprocess.check_output(["ip", "neigh"], text=True, timeout=5)
        for line in output.strip().splitlines():
            parts = line.split()
            # Format: IP dev IFACE lladdr MAC STATE
            if "lladdr" in parts:
                ip = parts[0]
                mac_idx = parts.index("lladdr") + 1
                if mac_idx < len(parts):
                    mac = parts[mac_idx].upper()
                    state = parts[-1]
                    if state != "FAILED" and mac not in seen:
                        seen[mac] = {"ip": ip, "mac": mac}
    except Exception:
        pass

    # Method 3: Add the local machine itself
    local = _get_local_info()
    if local and local["mac"] not in seen:
        seen[local["mac"]] = local

    return list(seen.values())


def _quick_scan_impl(network_cidr: str) -> dict:
    """
    Quick scan: host discovery + hostname resolution + vendor lookup.
    Returns summary dict.
    """
    scan_time = datetime.now(timezone.utc)
    hosts = _discover_hosts(network_cidr)

    new_devices = 0
    updated_devices = 0
    devices_found = []

    for host in hosts:
        mac = host["mac"]
        ip = host["ip"]

        device = Device.query.filter_by(mac_address=mac).first()

        hostname = _resolve_hostname(ip)
        vendor = _get_mac_vendor(mac)

        if device is None:
            device = Device(
                mac_address=mac,
                ip_address=ip,
                hostname=hostname or None,
                vendor=vendor or None,
                first_seen=scan_time,
                last_seen=scan_time,
                is_online=True,
            )
            db.session.add(device)
            new_devices += 1
        else:
            device.ip_address = ip
            device.last_seen = scan_time
            device.is_online = True
            if hostname and not device.hostname:
                device.hostname = hostname
            if vendor and not device.vendor:
                device.vendor = vendor
            updated_devices += 1

        db.session.flush()

        record = ScanRecord(
            device_id=device.id,
            ip_address=ip,
            scan_time=scan_time,
            scan_type="quick",
        )
        db.session.add(record)
        devices_found.append(device)

    # Mark devices not seen in this scan as offline
    seen_macs = {h["mac"] for h in hosts}
    all_devices = Device.query.filter_by(is_online=True).all()
    for dev in all_devices:
        if dev.mac_address not in seen_macs:
            dev.is_online = False

    db.session.commit()

    return {
        "scan_time": scan_time.isoformat(),
        "scan_type": "quick",
        "hosts_found": len(hosts),
        "new_devices": new_devices,
        "updated_devices": updated_devices,
        "devices": [d.to_dict() for d in devices_found],
    }


_DEEP_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deep_worker.py")


def _run_deep_worker(target: str) -> list[dict]:
    """
    Run nmap -O -sV in a separate Python process and return its parsed hosts.
    A /24 deep scan is the memory peak of the app (nmap + its XML output +
    python-nmap's parse). In a child process that memory is returned to the
    OS on exit, and the child marks itself as the OOM killer's first choice,
    so an OOM during the scan kills the scan, not the web app.
    """
    timeout = current_app.config.get("DEEP_SCAN_TIMEOUT", 1800)
    proc = subprocess.run(
        # Run by path, not "-m app...": no Flask/SQLAlchemy import in the child
        [sys.executable, _DEEP_WORKER, target],
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        hint = " (killed: out of memory?)" if proc.returncode == -9 else ""
        raise RuntimeError(
            f"deep scan worker exited with {proc.returncode}{hint}: "
            f"{proc.stderr.strip()[-500:]}"
        )
    return json.loads(proc.stdout)


def purge_old_scan_records(retention_days: int) -> int:
    """
    Delete ScanRecord rows older than retention_days; return how many.
    Every quick scan adds one row per host seen, and nothing ever removed
    them (~700k rows after 7 months). The UI only reads the latest 100-200.
    """
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    # Bulk SQL DELETE: rows are never loaded into Python
    deleted = (
        ScanRecord.query.filter(ScanRecord.scan_time < cutoff)
        .delete(synchronize_session=False)
    )
    db.session.commit()
    return deleted


def _deep_scan_impl(network_cidr: str, target_ip: str | None = None) -> dict:
    """
    Deep scan: OS detection + port scan on a single target or whole network.
    Requires root/sudo for OS detection.
    """
    scan_time = datetime.now(timezone.utc)
    target = target_ip or network_cidr

    devices_updated = []

    for host in _run_deep_worker(target):
        ip = host["ip"]
        mac = host["mac"]

        # Try to find device by MAC first, then by IP
        device = None
        if mac:
            device = Device.query.filter_by(mac_address=mac).first()
        if device is None:
            device = Device.query.filter_by(ip_address=ip).first()
        if device is None:
            continue

        if host["os_info"]:
            device.os_info = host["os_info"]
        if host["ports"]:
            device.open_ports = json.dumps(host["ports"])

        device.last_seen = scan_time
        device.is_online = True

        record = ScanRecord(
            device_id=device.id,
            ip_address=ip,
            scan_time=scan_time,
            scan_type="deep",
        )
        db.session.add(record)
        devices_updated.append(device)

    db.session.commit()

    return {
        "scan_time": scan_time.isoformat(),
        "scan_type": "deep",
        "devices_scanned": len(devices_updated),
        "devices": [d.to_dict() for d in devices_updated],
    }


# --- Public wrappers with event logging ---


def quick_scan(network_cidr: str) -> dict:
    """Run a quick scan and log the outcome as a ScanEvent."""
    started_at = datetime.now(timezone.utc)
    try:
        result = _quick_scan_impl(network_cidr)
        status = "success" if result["hosts_found"] > 0 else "partial"
        message = (
            f"Found {result['hosts_found']} hosts "
            f"({result['new_devices']} new, {result['updated_devices']} updated)"
        )
        event = _record_event(
            "quick", network_cidr, started_at, status, message,
            hosts_found=result["hosts_found"],
            new_devices=result["new_devices"],
        )
        result["event_id"] = event.id
        return result
    except Exception as e:
        db.session.rollback()
        err_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        _record_event("quick", network_cidr, started_at, "failed", err_msg)
        raise


def deep_scan(network_cidr: str, target_ip: str | None = None) -> dict:
    """Run a deep scan and log the outcome as a ScanEvent."""
    started_at = datetime.now(timezone.utc)
    target = target_ip or network_cidr
    try:
        result = _deep_scan_impl(network_cidr, target_ip)
        count = result["devices_scanned"]
        status = "success" if count > 0 else "partial"
        message = (
            f"Deep scan analyzed {count} device(s)"
            if count > 0
            else "Deep scan completed but no devices were analyzed "
                 "(check nmap permissions or target reachability)"
        )
        event = _record_event(
            "deep", target, started_at, status, message,
            hosts_found=count,
        )
        result["event_id"] = event.id
        return result
    except Exception as e:
        db.session.rollback()
        err_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        _record_event("deep", target, started_at, "failed", err_msg)
        raise
