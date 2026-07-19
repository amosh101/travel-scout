"""Restart the travel-api container with the right env.

Strategy: read the real .env, only swap the hostname of the two URLs
that point at compose hostnames (postgres, redis), and write the result
to a fresh file that docker reads. This avoids ever having to type a
real password in this script.
"""
from __future__ import annotations
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import json

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
REAL_ENV = os.path.join(PROJECT_ROOT, ".env")

# Map of compose hostnames -> host.docker.internal (override target).
HOST_SWAPS = {
    "postgres": "host.docker.internal",
    "redis": "host.docker.internal",
}


def patch_env_value(line: str) -> str:
    """If this line is DATABASE_URL / DATABASE_URL_SYNC / REDIS_URL and
    its host part is one of the compose names, swap it to host.docker.internal.
    Leave the password / port / database name untouched.
    """
    if "=" not in line:
        return line
    key, value = line.split("=", 1)
    key = key.strip()
    if key not in ("DATABASE_URL", "DATABASE_URL_SYNC", "REDIS_URL"):
        return line
    # Match a URL of the form  scheme://user:pass@HOST:port/db
    m = re.match(
        r"^(?P<scheme>[a-z+]+)://(?P<userpass>[^@/]+)@(?P<host>[^:/]+)(?P<rest>.*)$",
        value,
    )
    if not m:
        return line
    host = m.group("host")
    if host in HOST_SWAPS:
        new_value = (
            f"{m.group('scheme')}://{m.group('userpass')}@"
            f"{HOST_SWAPS[host]}{m.group('rest')}"
        )
        print(f"  swap {key}: host {host!r} -> {HOST_SWAPS[host]!r}")
        return f"{key}={new_value}"
    return line


def main() -> int:
    if not os.path.isfile(REAL_ENV):
        print(f".env not found at {REAL_ENV}")
        return 1

    with open(REAL_ENV) as f:
        original = f.read().splitlines()

    patched = [patch_env_value(l) for l in original]

    # Write to a temp file. Same line structure so comment lines are preserved.
    tmp = tempfile.NamedTemporaryFile(
        mode="w", delete=False, prefix="travel-api-env-", suffix=".env"
    )
    for line in patched:
        tmp.write(line + "\n")
    tmp.close()
    print(f"  wrote {tmp.name}")

    # Stop the old container, start the new one with this env file.
    subprocess.run(
        ["docker", "rm", "-f", "travel-api"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    cmd = [
        "docker", "run", "-d",
        "--name", "travel-api",
        "--restart", "unless-stopped",
        "--add-host=host.docker.internal:host-gateway",
        "--network", "bridge",
        "-p", "8000:8000",
        f"--env-file={tmp.name}",
        "travel-scout_api:latest",
    ]
    print("  starting container...")
    subprocess.run(cmd, check=True)

    # Wait for healthy.
    login_body = json.dumps(
        {"email": "amos@local.test", "password": "lQASfz9gdCwmmBt5-V8Q"}
    ).encode()
    for i in range(1, 11):
        time.sleep(1)
        try:
            req = urllib.request.Request(
                "http://localhost:8000/api/auth/login",
                data=login_body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=2) as r:
                body = json.loads(r.read())
                if "access_token" in body:
                    print(f"  healthy after {i}s")
                    return 0
        except Exception as e:
            print(f"  attempt {i}: {type(e).__name__}")

    print("  not healthy after 10s; logs:")
    subprocess.run(["docker", "logs", "travel-api", "--tail", "20"])
    return 1


if __name__ == "__main__":
    sys.exit(main())
