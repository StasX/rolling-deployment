import os
import boto3
import argparse
from utils.ansible import deploy_services, load_deployment_config
from utils.backend import prepare_backend
from utils.terraform import run_terraform, get_hosts
from pathlib import Path


AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
REGION = os.getenv("REGION", "us-east-1")
PROJECT_NAME = os.getenv("PROJECT_NAME")

BASE_DIR = Path(__file__).resolve().parent
INFRA_DIR = BASE_DIR / "infra"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        dest="apply_changes",
        action="store_true",
        help="Apply Terraform changes and deploy all services",
    )
    parser.add_argument(
        "--config", type=Path, default=BASE_DIR / "deployment.json",
        help="JSON file with deployment settings",
    )
    parser.add_argument(
        "--initialize-database", action="store_true",
        help="Bootstrap Galera on the seed node for a new cluster",
    )
    args = parser.parse_args()
    if args.initialize_database and not args.apply_changes:
        parser.error("--initialize-database requires --apply")

    if not PROJECT_NAME:
        raise ValueError("Environment variable PROJECT_NAME must be set.")

    if args.apply_changes:
        deployment_config = load_deployment_config(args.config, BASE_DIR, PROJECT_NAME)

    session = boto3.Session(
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        region_name=REGION,
    )
    s3_client = session.client("s3")

    prepare_backend(s3_client, PROJECT_NAME=PROJECT_NAME, REGION=REGION)

    run_terraform(
        "init",
        f"-backend-config=bucket={PROJECT_NAME}",
        "-backend-config=key=env/terraform.tfstate",
        f"-backend-config=region={REGION}",
        "-backend-config=use_lockfile=true",
        INFRA_DIR=INFRA_DIR
    )

    run_terraform("plan", "-out=tfplan", INFRA_DIR=INFRA_DIR)

    if args.apply_changes:
        run_terraform("apply", "tfplan", INFRA_DIR=INFRA_DIR)
        hosts = get_hosts(INFRA_DIR=INFRA_DIR)
        deploy_services(
            hosts, deployment_config, args.initialize_database,
            BASE_DIR=BASE_DIR, PROJECT_NAME=PROJECT_NAME, REGION=REGION,
        )


if __name__ == "__main__":
    main()
