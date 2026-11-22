"""Save the existing Compose project with its exact local images for rollback."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True)


def snapshot(project, runtime, destination):
    containers = docker("ps", "-aq", "--filter", f"label=com.docker.compose.project={project}").split()
    if not containers:
        return
    services = {}
    projects = set()
    for container in json.loads(docker("inspect", *containers)):
        labels = container["Config"]["Labels"]
        if labels.get("com.docker.compose.oneoff", "").lower() == "true":
            continue
        directory = labels["com.docker.compose.project.working_dir"]
        files = labels["com.docker.compose.project.config_files"]
        projects.add((directory, files, labels.get("com.docker.compose.project.environment_file")))
        service = labels["com.docker.compose.service"]
        image = container["Image"]
        if services.setdefault(service, image) != image:
            raise RuntimeError(f"Mixed images for service {service}")
    if not services:
        return
    if len(projects) != 1:
        raise RuntimeError("Existing containers use different Compose projects or releases.")
    directory, files, env_files = projects.pop()
    directory = Path(directory)
    args = ["compose", "--project-directory", str(directory), "-p", project]
    if env_files:
        for env_file in env_files.split(","):
            args.extend(["--env-file", env_file])
    elif not (directory / ".env").is_file() and (runtime / ".env").is_file():
        args.extend(["--env-file", str(runtime / ".env")])
    for file in files.split(","):
        args.extend(["-f", file])
    model = json.loads(docker(*args, "config", "--format", "json"))
    if services.keys() - model["services"].keys():
        raise RuntimeError("Existing services are missing from the saved Compose configuration.")
    for service, settings in model["services"].items():
        settings.pop("build", None)
        settings.pop("env_file", None)
        settings["pull_policy"] = "never"
        if service in services:
            tag = f"{project}-rollback:{hashlib.sha256(service.encode()).hexdigest()[:16]}"
            docker("tag", services[service], tag)
            settings["image"] = tag
        elif "image" not in settings:
            raise RuntimeError(f"No rollback image for service {service}")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.umask(0o077)
    pending = destination.with_suffix(".tmp")
    pending.write_text(json.dumps(model), encoding="utf-8")
    pending.replace(destination)


if __name__ == "__main__":
    snapshot(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]))
