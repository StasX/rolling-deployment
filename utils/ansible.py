import json
import os
import shutil
import subprocess  # nosec B404
from pathlib import Path
from tempfile import TemporaryDirectory

DEPLOYMENT_INPUT_TYPES = {
    "database_image": str,
    "database_wsrep_provider": str,
    "database_root_password": str,
    "database_password": str,
    "database_sst_password": str,
    "database_data_uid": int,
    "database_data_gid": int,
    "redis_image": str,
    "redis_sentinel_image": str,
    "redis_password": str,
    "redis_sentinel_password": str,
    "redis_data_uid": int,
    "redis_data_gid": int,
    "redis_sentinel_uid": int,
    "redis_sentinel_gid": int,
}
OPTIONAL_DEPLOYMENT_INPUT_TYPES = {
    "app_image": str,
    "app_container_port": int,
    "app_profile": str,
    "app_repo_url": str,
    "app_repo_version": str,
    "app_compose_file": str,
}


def find_ansible_playbook():
    executable = shutil.which("ansible-playbook")
    if executable is None:
        raise RuntimeError(
            "ansible-playbook is unavailable. "
            "Run this orchestration in Linux or WSL with Ansible installed."
        )
    return str(Path(executable).absolute())


def load_deployment_config(config_path, base_dir, project_name):
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid deployment JSON at line {error.lineno}, column {error.colno}."
        ) from None
    if not isinstance(config, dict):
        raise TypeError("Deployment configuration must be a JSON object.")

    invalid = []
    input_types = DEPLOYMENT_INPUT_TYPES | {
        name: kind for name, kind in OPTIONAL_DEPLOYMENT_INPUT_TYPES.items() if name in config
    }
    if "app_image" in config:
        default_profile = "image"
    else:
        default_profile = "compose"
        input_types["app_repo_url"] = str
        input_types["app_repo_version"] = str
    profile = config.get("app_profile", default_profile)
    for name, kind in input_types.items():
        value = config.get(name)
        if (
            type(value) is not kind
            or (kind is str and (not value.strip() or "\n" in value or "\r" in value))
            or (kind is int and value < 0)
        ):
            invalid.append(name)
    if (
        profile not in ("compose", "image")
        or (profile == "image") != ("app_image" in config)
    ) and "app_profile" not in invalid:
        invalid.append("app_profile")
    port = config.get("app_container_port", 8080)
    if type(port) is int and not 1 <= port <= 65535 and "app_container_port" not in invalid:
        invalid.append("app_container_port")
    if profile == "image" and "app_compose_file" in config and "app_compose_file" not in invalid:
        invalid.append("app_compose_file")
    if "database_allow_format" in config and type(config["database_allow_format"]) is not bool:
        invalid.append("database_allow_format")
    for name in (
        "database_bootstrap", "database_seed", "database_initialize_cluster",
        "database_managed_bootstrap", "database_finalize_bootstrap", "database_volume_device",
    ):
        if name in config:
            invalid.append(name)
    if invalid:
        raise ValueError("Missing or invalid deployment settings: " + ", ".join(invalid))

    ssh_key = base_dir / "keys" / f"{project_name}-key.pem"
    if not ssh_key.is_file():
        raise FileNotFoundError(f"SSH key not found: {ssh_key}")
    find_ansible_playbook()
    return config


def build_inventory(hosts, project_name, region, initialize_database):
    groups = {}
    for tier in ("database", "redis", "application"):
        addresses = hosts[tier]
        groups[tier] = {
            "hosts": {
                name: {"ansible_host": addresses["public_ips"][name]}
                for name in sorted(addresses["public_ips"])
            }
        }

    database_ips = hosts["database"]["private_ips"]
    database_seed = min(database_ips)
    groups["database"]["vars"] = {"database_cluster_nodes": list(database_ips.values())}
    for name, host in groups["database"]["hosts"].items():
        volume_id = hosts["database_volume_ids"][name].replace("-", "")
        host.update(
            database_node_name=name,
            database_node_private_ip=database_ips[name],
            database_volume_device=f"/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_{volume_id}",
            database_seed=name == database_seed,
        )

    redis_ips = hosts["redis"]["private_ips"]
    redis_primary_ip = redis_ips[min(redis_ips)]
    redis_sentinel_ips = [redis_ips[name] for name in sorted(redis_ips)]
    groups["redis"]["vars"] = {
        "redis_node_private_ips": redis_sentinel_ips,
        "redis_initial_primary_private_ip": redis_primary_ip,
    }
    for name, host in groups["redis"]["hosts"].items():
        host.update(redis_node_name=name, redis_node_private_ip=redis_ips[name])

    groups["application"]["vars"] = {
        "app_url": hosts["app_url"],
        "db_host": database_ips[database_seed],
        "db_database": "{{ database_name | default(project_name | lower) }}",
        "db_username": "{{ database_user | default('app') }}",
        "redis_sentinel_ips": redis_sentinel_ips,
        "aws_region": region,
        "aws_uploads_bucket": hosts["uploads_bucket"],
    }
    groups["monitoring"] = {
        "hosts": {"monitor-1": {"ansible_host": hosts["monitoring"]["public_ip"]}},
        "vars": {
            "monitoring_node_exporter_targets": [
                f"{ip}:9100"
                for tier in ("application", "database", "redis")
                for ip in hosts[tier]["private_ips"].values()
            ]
        },
    }
    return {
        "all": {
            "vars": {
                "project_name": project_name,
                "redis_sentinel_master_name": f"{project_name.lower()}-redis",
                "database_initialize_cluster": initialize_database,
                "deployment_managed_inventory": True,
            },
            "children": groups,
        }
    }, database_seed


def deploy_services(hosts, deployment_config, initialize_database, BASE_DIR, PROJECT_NAME, REGION):
    ansible_playbook = find_ansible_playbook()
    ansible_dir = BASE_DIR / "ansible"
    ssh_key = BASE_DIR / "keys" / f"{PROJECT_NAME}-key.pem"
    inventory, database_seed = build_inventory(hosts, PROJECT_NAME, REGION, initialize_database)
    ansible_env = os.environ.copy()
    ansible_env["ANSIBLE_CONFIG"] = str(ansible_dir / "ansible.cfg")
    stages = [
        ("setup", "all", {}),
        ("database", "database", {"database_managed_bootstrap": True}),
        ("database", database_seed, {
            "database_managed_bootstrap": True, "database_finalize_bootstrap": True,
        }),
        ("redis", "redis", {}),
        ("monitoring", "monitoring", {}),
        ("deploy", "application", {}),
    ]
    with TemporaryDirectory(prefix="rolling-deployment-") as directory:
        inventory_path = Path(directory) / "inventory.yml"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
        config_path = Path(directory) / "settings.json"
        config_path.write_text(json.dumps(deployment_config), encoding="utf-8")
        config_path.chmod(0o600)
        private_key = Path(directory) / "ssh-key.pem"
        shutil.copyfile(ssh_key, private_key)
        private_key.chmod(0o600)
        for playbook, limit, variables in stages:
            print(f"Running {playbook}.yml on {limit}...", flush=True)
            # Run the locally selected executable and playbook without a shell.
            subprocess.run(  # nosec B603
                [
                    ansible_playbook, "-i", str(inventory_path),
                    "--private-key", str(private_key),
                    "--limit", limit,
                    "--extra-vars", f"@{config_path}",
                    "--extra-vars", json.dumps(variables),
                    str(ansible_dir / "playbooks" / f"{playbook}.yml"),
                ],
                cwd=ansible_dir,
                env=ansible_env,
                check=True,
            )
