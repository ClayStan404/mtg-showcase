from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def workflow_source(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_heartbeat_queries_success_conclusion_through_status_parameter():
    source = workflow_source("heartbeat.yml")

    assert "runs?status=success&per_page=1" in source
    assert "status=completed&conclusion=success" not in source
    assert 'run.get("conclusion") == "success"' in source


def test_data_sync_is_not_attached_to_pages_environment():
    source = workflow_source("auto-update.yml")
    build_job, deploy_job = source.split("\n  deploy-pages:\n", maxsplit=1)

    assert "\n    concurrency:\n      group: data-publish\n" in build_job
    assert "\n    environment:\n" not in build_job
    assert "uses: actions/deploy-pages@" not in build_job
    assert "\n    environment:\n      name: github-pages\n" in deploy_job
    assert "uses: actions/deploy-pages@v5" in deploy_job
