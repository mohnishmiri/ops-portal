#!/usr/bin/env python
"""Simple health check for backend API."""

import socket
import sys


def check_port(host, port):
    """Check if port is open."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        return result == 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    port = 8000
    if check_port("127.0.0.1", port):
        print(f"✓ Backend server is running on port {port}")
        sys.exit(0)
    else:
        print(f"✗ Backend server is NOT running on port {port}")
        sys.exit(1)
