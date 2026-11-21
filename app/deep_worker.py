"""
Deep scan worker, run as a child process by scanner._run_deep_worker.

Usage: python deep_worker.py <target>
Prints a JSON list of {ip, mac, os_info, ports} on stdout.

Deliberately standalone (no Flask / SQLAlchemy import): the parent owns the
database, this process only scans, and all its memory goes back to the OS
when it exits.
"""
import json
import sys

import nmap


def _volunteer_for_oom_killer():
    # Highest OOM score: if the pod runs out of memory during the scan, the
    # kernel kills this process (and nmap, which inherits the score) instead
    # of the web app. Raising one's own score needs no privilege.
    try:
        with open("/proc/self/oom_score_adj", "w") as f:
            f.write("1000")
    except OSError:
        pass  # not Linux, or /proc read-only: scan anyway


def scan(target: str) -> list[dict]:
    nm = nmap.PortScanner()
    try:
        nm.scan(hosts=target, arguments="-O -sV --top-ports 100 -T4")
    except nmap.PortScannerError:
        # OS detection requires root; fall back to service scan only
        nm.scan(hosts=target, arguments="-sV --top-ports 100 -T4")

    hosts = []
    for host in nm.all_hosts():
        addr = nm[host].get("addresses", {})

        os_info = ""
        os_matches = nm[host].get("osmatch", [])
        if os_matches:
            best = os_matches[0]
            os_info = f"{best.get('name', '')} ({best.get('accuracy', '')}%)"

        ports = []
        for proto in nm[host].all_protocols():
            for port in sorted(nm[host][proto].keys()):
                svc = nm[host][proto][port]
                ports.append({
                    "port": port,
                    "protocol": proto,
                    "state": svc.get("state", ""),
                    "service": svc.get("name", ""),
                    "version": svc.get("version", ""),
                })

        hosts.append({
            "ip": addr.get("ipv4", host),
            "mac": addr.get("mac", "").upper(),
            "os_info": os_info,
            "ports": ports,
        })
    return hosts


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: deep_worker.py <target>")
    _volunteer_for_oom_killer()
    json.dump(scan(sys.argv[1]), sys.stdout)
