def deploy_application(client, target_group_arn, instance_ids, run_app):
    """Replace one target at a time, restoring its previous release on failure."""
    group = {"TargetGroupArn": target_group_arn}
    drained = client.get_waiter("target_deregistered")
    healthy = client.get_waiter("target_in_service")

    for host, instance_id in sorted(instance_ids.items()):
        target = dict(group, Targets=[{"Id": instance_id, "Port": 80}])
        states = {
            entry["Target"]["Id"]: entry["TargetHealth"]["State"]
            for entry in client.describe_target_health(**group)["TargetHealthDescriptions"]
        }
        prior_state = states.get(instance_id)
        if prior_state == "healthy" and sum(state == "healthy" for state in states.values()) < 2:
            raise RuntimeError(f"Cannot drain {host}: no other healthy target.")

        run_app("snapshot", host)
        try:
            client.deregister_targets(**target)
            drained.wait(**target)
        except (Exception, KeyboardInterrupt):
            if prior_state not in (None, "unused", "draining"):
                client.register_targets(**target)
                if prior_state == "healthy":
                    healthy.wait(**target)
            raise

        try:
            run_app("deploy", host)
            client.register_targets(**target)
            healthy.wait(**target)
        except (Exception, KeyboardInterrupt) as deployment_error:
            try:
                client.deregister_targets(**target)
                drained.wait(**target)
                run_app("rollback", host)
                client.register_targets(**target)
                healthy.wait(**target)
            except (Exception, KeyboardInterrupt) as rollback_error:
                client.deregister_targets(**target)
                raise RuntimeError(f"Deployment failed on {host}; rollback failed and the target was removed.") from rollback_error
            raise RuntimeError(f"Deployment failed on {host}; the previous release is healthy.") from deployment_error
