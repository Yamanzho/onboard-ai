from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.infra.compose_prod_env import COMPOSE_PROD_SECRETS

pytestmark = pytest.mark.infra
ROOT = Path(__file__).resolve().parents[2]


def test_required_alerts_and_safe_webhook_configuration_exist() -> None:
    alerts = (ROOT / "deploy/monitoring/alerts.yml").read_text()
    for name in (
        "PublicEndpointUnavailable",
        "ApiReadinessFailed",
        "PostgresDown",
        "DiskSpaceCritical",
        "BackupOverdue",
        "RestoreVerificationOverdue",
        "RestoreVerificationFailed",
        "TelegramOutboundBacklog",
        "TelegramPermanentFailuresRising",
        "KBIndexingFailed",
        "KBIndexingStuck",
        "AIProviderErrorsElevated",
        "TelegramBotDown",
        "RedisUnavailable",
        "HTTP5xxRateHigh",
        "KBReindexRequired",
        "IdempotencyStaleLeases",
        "TLSCertificateExpiringWarning",
        "TLSCertificateExpiringCritical",
        "ContainerRestartLoop",
        "HostCPUHigh",
        "HostLoadHigh",
    ):
        assert f"alert: {name}" in alerts
    assert "for:" in alerts
    assert "[10m]" in alerts
    # Phase 8A schedule: backups every 6h, restore verify daily.
    # Alert after 8h / 36h so one missed run is visible without timer-jitter noise.
    assert "onboardai_backup_last_success_timestamp_seconds > 28800" in alerts
    assert (
        "onboardai_restore_verification_last_success_timestamp_seconds > 129600"
        in alerts
    )
    assert "rate(node_cpu_seconds_total{mode=\"idle\"}[5m])" in alerts
    assert "node_load1" in alerts

    alertmanager = (ROOT / "deploy/monitoring/alertmanager.yml").read_text()
    assert "url_file: /run/secrets/alertmanager_webhook_url" in alertmanager
    assert "BOT_TOKEN" not in alertmanager
    assert "https://api.telegram.org" not in alertmanager


def test_public_nginx_layers_explicitly_block_metrics() -> None:
    for relative in (
        "frontend/nginx.prod.conf",
        "deploy/nginx/onboardai.aoe.kz.conf",
        "deploy/nginx/onboardai.aoe.kz.https.conf",
    ):
        config = (ROOT / relative).read_text()
        assert "location = /metrics" in config
        assert "return 404;" in config
        assert "proxy_pass http://api:8000/metrics" not in config


@pytest.mark.skipif(not shutil.which("docker"), reason="Docker is unavailable")
def test_monitoring_compose_ports_and_network_are_private() -> None:
    env = {**os.environ, **COMPOSE_PROD_SECRETS}
    env["ALERTMANAGER_WEBHOOK_URL_FILE"] = "/tmp/onboardai-test-webhook-url"
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.prod.yml",
            "-f",
            "docker-compose.monitoring.yml",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    config = json.loads(result.stdout)
    services = config["services"]
    assert services["prometheus"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert services["alertmanager"]["ports"][0]["host_ip"] == "127.0.0.1"
    for name in ("node-exporter", "blackbox-exporter", "cadvisor"):
        assert not services[name].get("ports")
    assert config["networks"]["monitoring"]["internal"] is True
    assert not services["api"].get("ports")


def test_monitoring_config_has_no_embedded_credentials() -> None:
    content = "\n".join(
        path.read_text()
        for path in (
            ROOT / "docker-compose.monitoring.yml",
            ROOT / "deploy/monitoring/prometheus.yml",
            ROOT / "deploy/monitoring/alertmanager.yml",
            ROOT / "deploy/monitoring/blackbox.yml",
            ROOT / "deploy/monitoring/alerts.yml",
        )
    ).lower()
    for forbidden in (
        "bot_service_token:",
        "postgres_password:",
        "s3_secret",
        "authorization: bearer",
        "refresh_token",
        "prompt:",
    ):
        assert forbidden not in content
