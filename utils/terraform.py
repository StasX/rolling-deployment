import json
import shutil
import subprocess  # nosec B404
from pathlib import Path


def run_terraform(*arguments, capture_output=False, INFRA_DIR):
    executable = shutil.which("terraform")
    if executable is None:
        raise FileNotFoundError("terraform is unavailable on PATH.")
    terraform = str(Path(executable).absolute())

    # The executable is resolved locally and arguments are passed without a shell.
    return subprocess.run(  # nosec B603
        [
            terraform,
            f"-chdir={INFRA_DIR}",
            *arguments,
        ],
        check=True,
        capture_output=capture_output,
        text=True,
    )


def get_hosts(INFRA_DIR):
    result = run_terraform(
        "output", "-json", capture_output=True, INFRA_DIR=INFRA_DIR)
    outputs = json.loads(result.stdout)

    def output_value(name):
        if name not in outputs:
            raise ValueError(f"Missing Terraform output: {name}")

        return outputs[name]["value"]

    hosts = {
        "application": {
            "public_ips": output_value("app_public_ips"),
            "private_ips": output_value("app_private_ips"),
        },
        "database": {
            "public_ips": output_value("database_public_ips"),
            "private_ips": output_value("database_private_ips"),
        },
        "redis": {
            "public_ips": output_value("redis_public_ips"),
            "private_ips": output_value("redis_private_ips"),
        },
        "monitoring": {
            "public_ip": output_value("monitoring_public_ip"),
            "private_ip": output_value("monitoring_private_ip"),
        },
        "database_volume_ids": output_value("database_volume_ids"),
        "app_url": output_value("app_url"),
        "uploads_bucket": output_value("uploads_bucket"),
    }

    for group in ("application", "database", "redis"):
        public_ips = hosts[group]["public_ips"]
        private_ips = hosts[group]["private_ips"]

        if not public_ips or public_ips.keys() != private_ips.keys():
            raise ValueError(f"Incomplete Terraform host outputs: {group}")

        if not all(public_ips.values()) or not all(private_ips.values()):
            raise ValueError(f"Missing IP addresses for {group} hosts.")

    if not all(hosts["monitoring"].values()):
        raise ValueError("Missing monitoring IP addresses.")

    volume_ids = hosts["database_volume_ids"]
    if (
        volume_ids.keys() != hosts["database"]["public_ips"].keys()
        or not all(volume_ids.values())
    ):
        raise ValueError("Incomplete Terraform database volume outputs.")

    return hosts
