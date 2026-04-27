import json
import socket
import subprocess
import traceback
from datetime import datetime, timezone

import nmap

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


def _get_mac_vendor(mac: str) -> str:
    """Try to resolve MAC vendor using mac-vendor-lookup."""
    try:
        from mac_vendor_lookup import MacLookup
        return MacLookup().lookup(mac)
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


def _deep_scan_impl(network_cidr: str, target_ip: str | None = None) -> dict:
    """
    Deep scan: OS detection + port scan on a single target or whole network.
    Requires root/sudo for OS detection.
    """
    scan_time = datetime.now(timezone.utc)
    nm = nmap.PortScanner()

    target = target_ip or network_cidr
    try:
        nm.scan(hosts=target, arguments="-O -sV --top-ports 100 -T4")
    except nmap.PortScannerError:
        # OS detection requires root; fall back to service scan only
        nm.scan(hosts=target, arguments="-sV --top-ports 100 -T4")

    devices_updated = []

    for host in nm.all_hosts():
        addr = nm[host].get("addresses", {})
        ip = addr.get("ipv4", host)
        mac = addr.get("mac", "").upper()

        # Try to find device by MAC first, then by IP
        device = None
        if mac:
            device = Device.query.filter_by(mac_address=mac).first()
        if device is None:
            device = Device.query.filter_by(ip_address=ip).first()
        if device is None:
            continue

        # OS info
        os_matches = nm[host].get("osmatch", [])
        if os_matches:
            best = os_matches[0]
            device.os_info = f"{best.get('name', '')} ({best.get('accuracy', '')}%)"

        # Open ports
        ports_info = []
        for proto in nm[host].all_protocols():
            for port in sorted(nm[host][proto].keys()):
                svc = nm[host][proto][port]
                ports_info.append({
                    "port": port,
                    "protocol": proto,
                    "state": svc.get("state", ""),
                    "service": svc.get("name", ""),
                    "version": svc.get("version", ""),
                })
        if ports_info:
            device.open_ports = json.dumps(ports_info)

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
