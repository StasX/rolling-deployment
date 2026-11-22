# RollingDeployment

AWS infrastructure and rolling deployment automation for containerized applications, with separate MariaDB Galera and Redis/Sentinel tiers and a [Monitoring](https://github.com/StasX/Monitoring) stack.

The project combines Terraform, Python (Boto3), Ansible, and Docker Compose to provision infrastructure, configure hosts, and deploy application releases incrementally.

## Architecture

One VPC spans two Availability Zones. Application, database, and Redis instances reside in AZ A; monitoring resides in AZ B. The public Application Load Balancer uses subnets in both AZs.

| Location | Component | Count | Purpose |
| --- | --- | ---: | --- |
| AZ A | Application EC2 | 3 | Run the application behind the ALB |
| AZ A | Database EC2 | 3 | Run a MariaDB Galera cluster |
| AZ A | Redis EC2 | 3 | One Redis instance and one Sentinel container per host |
| AZ B | Monitoring EC2 | 1 | Run Prometheus and Grafana |
| **Total EC2** | | **10** | Nine hosts in AZ A, one in AZ B |
| AZ A + AZ B | Application Load Balancer | 1 | Route HTTP requests to application instances |

```mermaid
flowchart TD
    Clients[Clients] --> ALB[Public ALB]
    subgraph A[AZ A]
    Apps[Three application instances] --> DB[Three Galera database nodes]
    Apps --> Redis[Redis primary and two replicas]
    Sentinel[Three Sentinels] -. Monitor and fail over .-> Redis
    end
    subgraph B[AZ B]
        Monitor[Prometheus and Grafana]
    end
    ALB --> Apps
    Monitor -. Scrape metrics .-> Apps
    Monitor -. Scrape metrics .-> DB
    Monitor -. Scrape metrics .-> Redis
    Apps --> Uploads[S3 uploads]
    DB --> Backups[S3 database backups]
```

### Availability tradeoff

The three-node Galera cluster is designed to retain quorum after one database-node failure, provided the other two nodes remain connected. Application releases run one instance at a time; preserving service requires enough healthy capacity on the remaining instances.

All application, database, and Redis nodes share AZ A. An AZ A outage therefore stops the application, database, and Redis service. Monitoring in AZ B can remain running and detect the loss of its targets. This architecture prioritizes local database communication and instance-level resilience; it does not provide application availability through an AZ A outage.

An asynchronous MariaDB replica in AZ B is a possible future disaster-recovery extension. It is not part of the initial ten-instance layout.

### Networking and storage

- EC2 instances currently use public subnets and public IPs for controlled SSH access and outbound downloads.

- Application HTTP traffic is allowed from the ALB security group only.

- MariaDB connections use private IPs and port `3306`, allowed from the application security group.

- Galera traffic on `4567/TCP`, `4567/UDP`, `4568/TCP`, and `4444/TCP` is restricted to members of the database security group.

- Redis port `6379` permits application access and communication between Redis hosts. Sentinel port `26379` permits application discovery and communication between Redis hosts. Both use private addresses.
- Node Exporter port `9100` on application, database, and Redis hosts is allowed from the monitoring security group.

- SSH and Grafana access are restricted by `ADMIN_ALLOWED_CIDR`.

- Each database node has a separate encrypted 100 GiB `gp3` data volume. Formatting, mounting, and database storage configuration belong to host provisioning.

- Redis uses a persistent host directory on each EC2 root volume; dedicated Redis data volumes are not currently defined.
- EC2 root volumes are encrypted, and instance metadata requires IMDSv2.

- Set `TF_VAR_ACM_CERTIFICATE_ARN` to enable the public HTTPS listener. With a certificate configured, port 80 redirects to HTTPS.
- Terraform enables ALB and S3 access logs and sends VPC flow logs and WAF matches to CloudWatch Logs. The WAF managed rules run in count mode so matches can be reviewed before blocking is enabled. WAF and log delivery and storage can incur AWS charges. EC2 continues to use free basic monitoring.

## Technology stack

| Area | Technology | Responsibility |
| --- | --- | --- |
| Infrastructure | Terraform, AWS | VPC, subnets, EC2, ALB, EBS, IAM, S3, optional Route 53 |
| Orchestration | Python, Boto3 | Prepare state storage, run Terraform, build inventory, and deploy services |
| Host configuration | Ansible | Docker installation and application, database, Redis/Sentinel, and monitoring roles |
| Runtime | Docker Engine, Docker Compose | Run application, database, Redis, Sentinel, and monitoring containers |
| Database | MariaDB Galera | Three-node database tier with a custom container image |
| Shared state | Redis, Sentinel | Shared sessions, cache, and queues with primary/replica failover |
| Observability | Prometheus, Grafana, Node Exporter | Host metrics and dashboards |
| Local setup | Bash, PowerShell, WSL | Prepare tooling and invoke the bootstrap |

## Repository layout

| Path | Purpose |
| --- | --- |
| `infra/` | Terraform resource definitions and outputs |
| `config/` | S3 bucket security helper |
| `utils/backend.py` | Prepare and secure the state bucket |
| `utils/terraform.py` | Run Terraform and parse/validate host outputs |
| `utils/ansible.py` | Build the Ansible inventory and run each deployment stage |
| `ansible/ansible.cfg` | Ansible connection and role configuration |
| `ansible/playbooks/` | Setup, database, Redis, application, and monitoring playbooks |
| `ansible/roles/docker/` | Docker Engine and Compose installation |
| `ansible/roles/app/` | Application checkout, environment, Compose deployment, and health checks |
| `ansible/roles/database/` | EBS preparation, Galera configuration, and Compose deployment tasks |
| `ansible/roles/database_proxy/` | HAProxy and Galera health checks on each application host |
| `ansible/roles/redis/` | Redis/Sentinel initial configuration, persistence, and Compose deployment |
| `ansible/roles/monitoring/` | Monitoring repository checkout and Compose deployment |
| `scripts/` | Tool installation and SSH key generation |
| `keys/` | Locally generated SSH keys; private keys must stay out of Git |
| `main.py` | Orchestrate the backend, Terraform, host discovery, and service deployment |
| `deploy.sh`, `deploy.ps1` | Local setup entrypoints |
| `example.env` | Environment configuration template |

## Configuration

Copy the template and edit it before running the bootstrap:

```bash
cp example.env .env
```

PowerShell:

```powershell
Copy-Item example.env .env
```

| Variable | Example | Purpose |
| --- | --- | --- |
| `PROJECT_NAME` | `theschool-your-unique-suffix` | Resource identifier and current Terraform state bucket name; choose a globally unique, lowercase S3-compatible value |
| `REGION` | `us-east-1` | Region used by Boto3 and the Terraform backend |
| `AWS_DEFAULT_REGION` | `us-east-1` | AWS provider region; keep aligned with `REGION` |
| `TF_VAR_AVAILABILITY_ZONES` | `'["us-east-1a","us-east-1b"]'` | Two AWS Availability Zone names in subnet order. Application, database, and Redis hosts use the first zone and monitoring uses the second. |
| `TF_VAR_ACM_CERTIFICATE_ARN` | ACM certificate ARN | Certificate in the ALB region for the public application hostname |
| `MOST_RECENT` | `true` | Select the newest matching Ubuntu AMI |
| `AMI_ID` | empty | Optional explicit AMI ID |
| `USE_DOMAIN` | `false` | Enable the Route 53 application record |
| `DOMAIN_NAME` | empty | Existing public hosted-zone domain, required when `USE_DOMAIN=true` |
| `ADMIN_ALLOWED_CIDR` | `203.0.113.10/32` | Replace this documentation address with your actual administrator public IPv4 CIDR |

The entrypoint loads `.env` into the process environment. Boto3 and Terraform support temporary environment credentials through `AWS_SESSION_TOKEN`. Set `AWS_DEFAULT_REGION` or configure the same region in your AWS profile so the provider matches `REGION`.

Terraform rejects `ADMIN_ALLOWED_CIDR=0.0.0.0/0`; `0.0.0.0` without a prefix is also invalid. Use an appropriate restrictive CIDR.

For an existing deployment, set `TF_VAR_AVAILABILITY_ZONES` to the zones of `aws_subnet.public_sn[0]` and `aws_subnet.public_sn[1]` in that order. You can read each current `availability_zone` with `terraform -chdir=infra state show 'aws_subnet.public_sn[0]'` and the corresponding command for index 1. Check the plan for subnet replacements before applying.

Create a private `deployment.json` in the repository root, or pass `--config path/to/settings.json`. Replace the example strings and use the numeric UIDs/GIDs from the actual container images.

```json
{
  "app_repo_url": "https://example.com/team/my-app.git",
  "app_repo_version": "REPLACE_WITH_A_RELEASE_COMMIT_SHA",
  "database_image": "registry.example.com/galera:tested-release",
  "database_wsrep_provider": "/path/in/image/to/libgalera_smm.so",
  "database_root_password": "REPLACE",
  "database_password": "REPLACE",
  "database_sst_password": "REPLACE",
  "database_data_uid": 999,
  "database_data_gid": 999,
  "database_allow_format": true,
  "redis_image": "redis:YOUR_TESTED_TAG",
  "redis_sentinel_image": "redis:YOUR_TESTED_TAG",
  "redis_password": "REPLACE",
  "redis_sentinel_password": "REPLACE",
  "redis_data_uid": 999,
  "redis_data_gid": 999,
  "redis_sentinel_uid": 999,
  "redis_sentinel_gid": 999
}
```

Set `database_allow_format` to true only when provisioning the dedicated blank database volumes. The deployment locates those volumes by their Nitro EBS device IDs. The example uses the application's `docker-compose.yaml`. A monitoring checkout can be selected with `monitoring_repo_url`; its Compose file must have a service using `/etc/prometheus/prometheus.yml`. Use `monitoring_prometheus_service` if the service is named something other than `prometheus`.

## Local setup and execution

Requirements:

- An AWS account and credentials permitted to manage the defined resources.

- A region with at least two available AZs.

- Git and Bash on Linux, or PowerShell with a configured WSL Linux distribution on Windows.

- Access to AWS APIs, package repositories, and application repositories.

For the first deployment of a new database, run from the repository root:

```bash
bash ./deploy.sh --initialize-database
```

PowerShell entrypoint:

```powershell
.\deploy.ps1 --initialize-database
```

The PowerShell entrypoint runs the Bash workflow in the default WSL distribution. Both entrypoints load `.env` as shell syntax, prepare tooling and SSH keys, and apply and deploy in the same Linux environment.

For later releases, update `app_image` for image deployments or `app_repo_version` for repository deployments. Run the same command without `--initialize-database`.

For direct Python execution, after preparing the virtual environment and loading environment variables:

```bash
./env/bin/python main.py          # Create a Terraform plan
./env/bin/python main.py --apply  # Apply and run all service deployment stages
```

Without `--apply`, infrastructure resources are only planned, but the Python bootstrap can still create or update the S3 state bucket. With `--apply`, Python creates a new plan, applies it, reads host outputs, and invokes `setup.yml`; it does not reuse a plan reviewed during a previous invocation.

## Terraform state and host discovery

Python prepares an S3 bucket named by `PROJECT_NAME`, enables or checks public-access blocking and versioning, and initializes Terraform with:

- State key: `env/terraform.tfstate`

- Native S3 locking: `use_lockfile=true`

- Saved local plan: `infra/tfplan`

Host information is exposed through these Terraform outputs:

| Output | Use |
| --- | --- |
| `app_public_ips` | SSH access to application hosts |
| `app_private_ips` | Internal application addresses and monitoring targets |
| `database_public_ips` | SSH access to database hosts |
| `database_private_ips` | Galera membership, database connections, and monitoring targets |
| `app_instance_ids`, `app_target_group_arn` | Instance targets and target group for rolling ALB deployment |
| `redis_public_ips` | SSH access to Redis hosts |
| `redis_private_ips` | Redis replication, Sentinel discovery, and monitoring targets |
| `monitoring_public_ip` | SSH access and administrator Grafana access |
| `monitoring_private_ip` | Internal monitoring address |
| `app_url` | ALB or custom-domain application URL |

Python reads `terraform output -json` after a successful apply. Outputs include existing managed hosts even when no infrastructure changes occur. They are state values; `setup.yml` waits for Ansible connection readiness before gathering facts. SSH host trust must also be configured because host-key checking is enabled.

## Ansible workflow

After Terraform applies, Python builds a temporary inventory with named groups, public SSH addresses, private service addresses, EBS device paths, and monitoring targets. Each playbook is limited to its own group. A failed stage stops the workflow.

1. Wait for SSH and install Docker Engine, Compose, and Node Exporter on the scrape targets.
2. Provision Galera storage and start the database nodes in order. On initial deployment, start the seed in bootstrap mode, join the peers, then recreate the seed in normal mode.
3. Configure the initial Redis primary, then the replicas and Sentinels.
4. Start monitoring with the private Node Exporter targets.
5. Configure the local Galera proxy on each application host.
6. Release the application one host at a time, waiting for both local and ALB health checks before continuing.

## Database provisioning

The database role validates configuration and secrets, inspects the supplied EBS device, and formats a blank volume only when `database_allow_format` is enabled. It mounts by filesystem UUID and renders Galera, environment, and Compose templates.

The custom image must support the role's `GALERA_BOOTSTRAP` environment variable, database initialization and SST credentials, and `/usr/local/bin/galera-healthcheck` for Primary, ready, and Synced status. Bootstrap mode disables the seed container's automatic restart until the other members have joined. A rerun can continue with a healthy bootstrap seed. If that seed stops after writing database files, recover the cluster before retrying. Existing databases created with older versions of the role may have literal quote characters in credentials or identifiers because Compose preserves quotes in raw environment files. Reconcile those database values before switching the application to the new configuration.

Each application host runs HAProxy on its private IP, which is passed to its containers as `DB_HOST`. HAProxy prefers the first Galera node and uses the other nodes when it is unavailable. The health check requires a synchronized, ready, writable node in the Primary component. Applications must reconnect after a backend connection drops. [MariaDB Galera status variables](https://mariadb.com/resources/blog/setting-up-a-mariadb-enterprise-cluster-part-2-how-to-set-up-a-mariadb-cluster/)

## Redis and Sentinel

Three dedicated Redis EC2s in AZ A each run Redis and Sentinel containers. The initial topology is one primary and two replicas, with three Sentinels and quorum set to two. This is a replicated Redis deployment, not a sharded Redis Cluster.

Host networking and private address announcements make discovered endpoints reachable inside the VPC. Redis data and writable configuration live in persistent host directories. Initial configuration templates use `force: false` so subsequent runs preserve rewritten replication and Sentinel state. Password rotation and topology changes need deliberate maintenance rather than reapplying the initial configuration.

Redis uses AOF persistence with `appendfsync everysec` and a `noeviction` policy. Persistence and asynchronous replication do not guarantee zero data loss during failures. Local PING health checks establish responsiveness; final validation must check replica links, Sentinel agreement, and failover behavior.

Applications receive the same Redis settings through either profile.

| Environment variable | Value |
| --- | --- |
| `REDIS_SENTINEL_HOSTS` | All three private Sentinel IP addresses, comma-separated |
| `REDIS_SENTINEL_PORT` | Sentinel port, defaulting to `26379` |
| `REDIS_SENTINEL_MASTER` | Monitored primary name, defaulting to lowercase `<project-name>-redis` |
| `REDIS_SENTINEL_PASSWORD` | Password for Sentinel discovery |
| `REDIS_PASSWORD` | Password for the Redis primary |

For an existing cluster, use the monitored name and port already in the persisted Sentinel configuration. Supply the three endpoints and the monitored name to the application's Sentinel client. Use the Sentinel password for discovery and the Redis password for the resulting primary connection.

| Runtime | Sentinel client |
| --- | --- |
| Python | [redis-py `Sentinel.master_for()`](https://redis.io/docs/latest/develop/clients/redis-py/connect/) |
| PHP | [Predis Sentinel replication](https://redis.io/docs/latest/develop/clients/php/connect/) |
| JavaScript / Node.js | [ioredis Sentinel mode](https://github.com/redis/ioredis#sentinel) |
| Java | [Jedis `RedisSentinelClient`](https://redis.io/docs/latest/develop/clients/jedis/connect/) |
| C# / .NET | [StackExchange.Redis Sentinel mode](https://github.com/StackExchange/StackExchange.Redis/blob/main/docs/Configuration.md) |

## Application releases

The application role deploys a prebuilt image or checks out a repository and deploys its Compose services. The deployment playbook processes one application host at a time and stops subsequent batches on failure.

For a prebuilt Docker image, add these settings to `deployment.json`. The image can use any language or framework.

```json
{
  "app_image": "registry.example.com/team/my-app:1.2.3",
  "app_container_port": 8080
}
```

Setting `app_image` selects the image profile. RollingDeployment pulls the image, passes the shared environment to the container, and publishes its configured port on host port `80`. The process in the image must listen on `0.0.0.0` and return HTTP 200 from `/api/health`. For a private registry, the application hosts' Docker client needs pull access.

To replace one application with another on the same stack, change `app_image` and redeploy. Keep `app_container_port` the same if both images use the same internal port. Both images receive the same MariaDB connection settings (`DB_HOST`, `DB_PORT`, `DB_DATABASE`, `DB_USERNAME`, and `DB_PASSWORD`) and the same Redis Sentinel settings listed above. During a rolling replacement, both versions must be compatible with the shared database schema and any sessions, cache entries, or queued jobs they share.

With the `compose` profile, set `app_repo_url` and `app_repo_version`. The deployment uses `docker-compose.yaml` unless `app_compose_file` specifies a different filename. Set `"app_env_services": ["web", "worker"]` in `deployment.json` to inject the environment into those existing Compose services. Alternatively, add `env_file` to the services in your own Compose file. Ansible also passes the generated file to Compose for interpolation. Compose's service-level `environment` entries still take precedence. [Docker Compose environment precedence](https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/)

```yaml
services:
  web:
    build: .
    pull_policy: build
    env_file:
      - "${APP_RUNTIME_ENV_FILE:?RollingDeployment environment file is required}"
    ports:
      - "80:8080"
```

The infrastructure routes to host port `80` and checks `/api/health`. Expose that endpoint from the web service. Workers can use the same `env_file` in their own Compose services.

The deployment requires an active ALB listener and AWS credentials with `DescribeTargetGroups`, `DescribeTargetHealth`, `DeregisterTargets`, and `RegisterTargets` access. The controller saves the running Compose model and image IDs, drains one target, deploys and checks the local HTTP endpoint, then registers the target and waits for ALB health. It will stop before draining the last healthy target. [ALB connection draining](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/edit-target-group-attributes.html)

If a deployment fails, the controller restores the previous release on that host and stops the rollout. Earlier hosts that passed health checks keep the new release. A target whose rollback fails stays out of service. On a first deployment there is no previous release to restore. Rollback covers Compose configuration, images, and versioned source files. Shared volumes and database changes need their own recovery strategy. Keep release files and local rollback images available, and run only one rollout against a target group at a time.

Database schema changes need a separate migration strategy compatible with both old and new application versions.

## Tests

`python -m unittest discover -s tests` checks deployment profiles, Sentinel inventory, and ALB rollout and rollback ordering. `python tests/redis_failover.py` starts a Dockerized HTTP app, three Redis servers, and three Sentinels on an isolated network. It stops the Redis primary and one Sentinel, then verifies recovery through the same HTTP container, including data written before promotion and new writes afterward.

## IAM and backups

| Host role | Permissions |
| --- | --- |
| Application | SSM and access to the uploads bucket |
| Database | SSM and backup uploads to the database backups bucket |
| Redis | SSM |
| Monitoring | SSM |

Creating the backups bucket and granting `s3:PutObject` does not create a backup process. Scheduling backups, recording their success, and testing restoration remain necessary. Downloading backups for restoration requires additional read permissions.

## Infrastructure changes and cleanup

Many resources use `prevent_destroy`, and the ALB enables deletion protection. Moving existing instances between subnets, removing hosts, or changing database volume keys can require destructive actions that these protections block. Review the Terraform plan and prepare any data migration before changing those protections.

Provisioned resources incur ongoing charges. Keep `.env`, private keys, Terraform state, and saved plans out of Git, and protect application secrets supplied to Ansible. Public IPs provide reachability; security groups define the permitted inbound access.

## License

[Apache License 2.0](LICENSE).
