#!/usr/bin/env python3
"""LanEyes - Network Monitor. Run with sudo for full scan capabilities."""

from app import create_app

app = create_app()

if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"\n  LanEyes running at http://localhost:{port}")
    print(f"  Network: {app.config['NETWORK_CIDR']}")
    print(f"  Run with sudo for OS detection (deep scan)\n")
    app.run(host="0.0.0.0", port=port, debug=True)
