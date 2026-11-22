import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from utils.ansible import (
    DEPLOYMENT_INPUT_TYPES,
    build_inventory,
    load_deployment_config,
)
from utils.rolling import deploy_application


class DeploymentConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        (self.directory / "keys").mkdir()
        (self.directory / "keys/example-key.pem").touch()
        self.config = self.directory / "deployment.json"
        self.base = {
            name: "value" if kind is str else 1000 for name, kind in DEPLOYMENT_INPUT_TYPES.items()
        }

    def load(self, **settings):
        self.config.write_text(json.dumps(self.base | settings), encoding="utf-8")
        with patch("utils.ansible.find_ansible_playbook"):
            return load_deployment_config(self.config, self.directory, "example")

    def test_image_profile_requires_no_checkout(self):
        self.assertEqual(self.load(app_image="example/app:v1")["app_image"], "example/app:v1")

    def test_compose_services(self):
        config = self.load(app_repo_url="https://example.com/app.git", app_repo_version="v1",
                           app_env_services=["web", "worker.jobs"])
        self.assertEqual(config["app_env_services"], ["web", "worker.jobs"])

    def test_invalid_profile_settings(self):
        for expected, settings in (
            ("app_repo_url", {}),
            ("app_profile", {"app_image": "example/app:v1", "app_profile": "compose"}),
            ("app_container_port", {"app_image": "example/app:v1", "app_container_port": 65536}),
            ("app_env_services", {"app_image": "example/app:v1", "app_env_services": ["web"]}),
            ("app_env_services", {"app_repo_url": "https://example.com/app.git",
                                  "app_repo_version": "v1", "app_env_services": ["bad name"]}),
        ):
            with self.subTest(settings=settings), self.assertRaisesRegex(ValueError, expected):
                self.load(**settings)


def tier(prefix, subnet):
    return {
        "private_ips": {f"{prefix}-{i}": f"10.0.{subnet}.{i}" for i in (3, 1, 2)},
        "public_ips": {f"{prefix}-{i}": f"192.0.2.{i}" for i in (3, 1, 2)},
    }


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.hosts = {
            "database": tier("db", 1), "redis": tier("redis", 2), "application": tier("app", 3),
            "database_volume_ids": {f"db-{i}": f"vol-{i}" for i in (1, 2, 3)},
            "app_url": "https://example.com", "uploads_bucket": "uploads",
            "monitoring": {"public_ip": "192.0.2.10"},
        }

    def test_sentinel_inventory_and_local_database_proxy(self):
        inventory, seed = build_inventory(self.hosts, "Example", "us-east-1", False)
        root = inventory["all"]
        application = root["children"]["application"]
        self.assertEqual(seed, "db-1")
        self.assertEqual(root["vars"]["redis_sentinel_master_name"], "example-redis")
        self.assertEqual(application["vars"]["redis_sentinel_ips"], ["10.0.2.1", "10.0.2.2", "10.0.2.3"])
        self.assertEqual(application["vars"]["app_database_backends"], ["10.0.1.1", "10.0.1.2", "10.0.1.3"])
        self.assertEqual(application["hosts"]["app-2"]["db_host"], "10.0.3.2")

    def test_reject_duplicate_sentinel_ips(self):
        self.hosts["redis"]["private_ips"]["redis-2"] = self.hosts["redis"]["private_ips"]["redis-1"]
        with self.assertRaisesRegex(ValueError, "three distinct"):
            build_inventory(self.hosts, "Example", "us-east-1", False)


class RollingTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.client = Mock()
        self.client.get_waiter.side_effect = lambda name: Mock(
            wait=lambda **kwargs: self.events.append(name)
        )
        self.client.describe_target_health.return_value = {
            "TargetHealthDescriptions": [
                {"Target": {"Id": name}, "TargetHealth": {"State": "healthy"}}
                for name in ("i-1", "i-2")
            ]
        }
        self.client.deregister_targets.side_effect = lambda **kwargs: self.events.append("deregister")
        self.client.register_targets.side_effect = lambda **kwargs: self.events.append("register")

    def test_drains_and_waits_before_next_host(self):
        deploy_application(self.client, "tg", {"app-2": "i-2", "app-1": "i-1"},
                           lambda phase, host: self.events.append((phase, host)))
        for index, host in ((0, "app-1"), (6, "app-2")):
            self.assertEqual(self.events[index:index + 6], [
                ("snapshot", host), "deregister", "target_deregistered",
                ("deploy", host), "register", "target_in_service",
            ])

    def test_failed_deployment_restores_previous_release(self):
        def deploy(phase, host):
            self.events.append((phase, host))
            if phase == "deploy":
                raise RuntimeError("bad release")

        with self.assertRaisesRegex(RuntimeError, "previous release is healthy"):
            deploy_application(self.client, "tg", {"app-1": "i-1", "app-2": "i-2"}, deploy)
        self.assertEqual(self.events[-3:], [("rollback", "app-1"), "register", "target_in_service"])
        self.assertNotIn(("snapshot", "app-2"), self.events)

    def test_last_healthy_target_is_not_drained(self):
        states = self.client.describe_target_health.return_value["TargetHealthDescriptions"]
        states.pop()
        with self.assertRaisesRegex(RuntimeError, "no other healthy"):
            deploy_application(self.client, "tg", {"app-1": "i-1"}, Mock())
        self.assertEqual(self.events, [])

    def test_alb_health_failure_triggers_rollback(self):
        health_waiter = Mock()
        health_waiter.wait.side_effect = [RuntimeError("failed ALB health check"), None]
        self.client.get_waiter.side_effect = lambda name: (
            health_waiter if name == "target_in_service" else Mock()
        )
        run_app = Mock()
        with self.assertRaisesRegex(RuntimeError, "previous release is healthy"):
            deploy_application(self.client, "tg", {"app-1": "i-1"}, run_app)
        self.assertEqual([phase.args[0] for phase in run_app.call_args_list], ["snapshot", "deploy", "rollback"])
        self.assertEqual(health_waiter.wait.call_count, 2)

    def test_rollback_failure_leaves_target_deregistered(self):
        failed = Mock(side_effect=[None, RuntimeError("deploy"), RuntimeError("rollback")])
        with self.assertRaisesRegex(RuntimeError, "rollback failed"):
            deploy_application(self.client, "tg", {"app-1": "i-1"}, failed)
        self.assertEqual(self.events[-1], "deregister")
        self.client.register_targets.assert_not_called()
