"""Stop an isolated Redis primary and verify recovery from a live HTTP container."""

import json
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4


def poll(check, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.5)
    raise RuntimeError("Timed out waiting for the failover test condition")


def verify(directory):
    project = f"sentinel-test-{uuid4().hex[:10]}"
    primary = "172.31.239.11"
    services = {}
    for i in range(1, 4):
        redis_ip = f"172.31.239.1{i}"
        sentinel_ip = f"172.31.239.2{i}"
        definitions = {
            f"redis-{i}": (redis_ip, "requirepass data-test\nmasterauth data-test\n"
                          f"replica-announce-ip {redis_ip}\nrepl-diskless-sync-delay 0\n"
                          + (f"replicaof {primary} 6379\n" if i > 1 else "")),
            f"sentinel-{i}": (sentinel_ip, (
                "port 26379\nrequirepass sentinel-test\n"
                f"sentinel announce-ip {sentinel_ip}\n"
                f"sentinel monitor app-redis {primary} 6379 2\n"
                "sentinel auth-pass app-redis data-test\n"
                "sentinel down-after-milliseconds app-redis 2000\n"
            )),
        }
        for name, (address, config) in definitions.items():
            fixture = directory / f"{name}.conf"
            fixture.write_text("bind 0.0.0.0\n" + config, encoding="ascii")
            services[name] = {
                "image": "redis:8-alpine",
                "volumes": [f"{fixture.as_posix()}:/fixture.conf:ro"],
                "networks": {"default": {"ipv4_address": address}},
                "entrypoint": ["sh", "-ec", "cp /fixture.conf /data/redis.conf; "
                               "exec docker-entrypoint.sh redis-server /data/redis.conf"
                               + (" --sentinel" if name.startswith("sentinel") else "")],
            }
    probe = Path(__file__).with_name("redis_probe.py").resolve()
    services["app"] = {
        "image": "python:3.13-alpine",
        "volumes": [f"{probe.as_posix()}:/probe.py:ro"],
        "ports": ["127.0.0.1::8080"],
        "entrypoint": ["sh", "-ec", "pip install --quiet redis==5.2.1; exec python /probe.py"],
        "environment": {
            "REDIS_SENTINEL_HOSTS": "172.31.239.21,172.31.239.22,172.31.239.23",
            "REDIS_SENTINEL_PORT": "26379",
            "REDIS_SENTINEL_MASTER": "app-redis",
            "REDIS_SENTINEL_PASSWORD": "sentinel-test",
            "REDIS_PASSWORD": "data-test",
        },
    }
    config = directory / "compose.json"
    config.write_text(json.dumps({
        "services": services,
        "networks": {"default": {"ipam": {"config": [{"subnet": "172.31.239.0/24"}]}}},
    }), encoding="utf-8")

    def compose(*args, capture=False):
        return subprocess.run(["docker", "compose", "-p", project, "-f", str(config), *args],
                              check=True, text=True, capture_output=capture).stdout

    def sentinel(*args):
        try:
            return compose("exec", "-T", "-e", "REDISCLI_AUTH=sentinel-test", "sentinel-2",
                           "redis-cli", "-p", "26379", "SENTINEL", *args, "app-redis", capture=True).strip()
        except subprocess.CalledProcessError:
            return ""

    try:
        compose("up", "-d")
        endpoint = compose("port", "app", "8080", capture=True).strip()

        def request(path, method):
            try:
                with urlopen(Request(f"http://{endpoint}/{path}", method=method), timeout=5) as response:
                    return response.read() if method == "POST" else response.status
            except OSError:
                return None

        poll(lambda: sentinel("CKQUORUM").startswith("OK 3"))
        if json.loads(poll(lambda: request("seed", "POST"))) != 2:
            raise RuntimeError("Both replicas must acknowledge the initial writes")
        before = compose("ps", "-q", "app", capture=True)
        compose("stop", "redis-1", "sentinel-1")

        def promoted_primary():
            address = sentinel("GET-MASTER-ADDR-BY-NAME").splitlines()
            return address[0] if address and address[0] in {"172.31.239.12", "172.31.239.13"} else None

        promoted = poll(promoted_primary)
        poll(lambda: request("api/health", "GET"))
        result = request("recover", "POST")
        if result is None or json.loads(result) != ["before"] * 3 + ["after"] * 3:
            raise RuntimeError(f"Expected session, cache and queue recovery, got {result!r}")
        if compose("ps", "-q", "app", capture=True) != before:
            raise RuntimeError("The HTTP app container was replaced")
        print(f"PASS: the same HTTP app recovered sessions, cache and queue on {promoted}")
    except Exception:
        compose("logs", "--tail", "30")
        raise
    finally:
        compose("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="sentinel-failover-") as temp:
        verify(Path(temp))
