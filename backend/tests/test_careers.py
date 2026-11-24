from __future__ import annotations

from fastapi.testclient import TestClient


def test_registry_offline_fallback(client: TestClient) -> None:
    res = client.get("/api/v1/registry")
    assert res.status_code == 200
    data = res.json()
    assert data["schema_version"] == "1.0"
    assert len(data["careers"]) >= 1
    assert data["careers"][0]["id"] == "cl-pucv-inf-2022"
    assert data["packs"] == []


def test_get_career_detail_and_bulk_status(client: TestClient) -> None:
    res = client.get("/api/v1/careers/cl-pucv-inf-2022")
    assert res.status_code == 200
    career = res.json()
    assert career["id"] == "cl-pucv-inf-2022"
    assert career["career"]["plan_ref"] == "DRA 6/2022 (mod. DRA 61/2020)"
    assert career["credits_passed"] == 0
    assert career["credits_total"] > 0
    assert career["statuses"]["MAT1001"] == "pending"
    assert career["statuses"]["ING9000"] == "pending"

    # Bulk approve S1..S3 (ING9000 in S3 is optional so it remains pending)
    bulk = client.post(
        "/api/v1/careers/cl-pucv-inf-2022/bulk-status",
        json={"up_to_semester": 3, "status": "passed"},
    )
    assert bulk.status_code == 200
    bdata = bulk.json()
    assert bdata["updated_count"] == 15  # 5 in S1 + 5 in S2 + 5 non-optional in S3

    # Calling a second time is idempotent (0 changed)
    bulk_again = client.post(
        "/api/v1/careers/cl-pucv-inf-2022/bulk-status",
        json={"up_to_semester": 3, "status": "passed"},
    )
    assert bulk_again.status_code == 200
    assert bulk_again.json()["updated_count"] == 0

    after = client.get("/api/v1/careers/cl-pucv-inf-2022").json()
    assert after["statuses"]["MAT1001"] == "passed"
    assert after["statuses"]["INF2322"] == "passed"
    assert after["statuses"]["ING9000"] == "pending"
    assert after["statuses"]["INF2324"] == "pending"
    assert after["credits_passed"] == 55


def test_get_unknown_career_returns_404(client: TestClient) -> None:
    res = client.get("/api/v1/careers/non-existent-career")
    assert res.status_code == 404
