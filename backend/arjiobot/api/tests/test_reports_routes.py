"""Report route tests."""

from arjiobot.api.demo_backend_api import build_validation_report
from arjiobot.api.tests.helpers import client


def test_report_listing_serving_and_validation_report_generation() -> None:
    report = build_validation_report()
    api = client()
    reports = api.get("/api/reports").json()["data"]
    served = api.get("/api/reports/backend_api_validation_report.html").json()["data"]

    assert report["html_path"].exists()
    assert report["png_path"].exists()
    assert any(item["report_name"] == "backend_api_validation_report.html" for item in reports)
    assert "Backend API Routes Validation Report" in served["content"]
    assert report["png_path"].read_bytes().startswith(b"\x89PNG")


def test_openapi_generation_and_guarded_live_routes() -> None:
    api = client()
    schema = api.get("/openapi.json").json()
    paths = schema["paths"]

    assert "/api/health" in paths
    assert "/api/execution/paper/{trade_plan_id}" in paths
    assert "/api/bitget/connection/live" in paths
    assert "/api/bitget/orders/live" in paths
