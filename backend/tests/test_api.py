"""API tests: the dashboard endpoints return the pipeline's results."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("apiroot")
    api.DATA_ROOT, api.OUTPUT_ROOT = root / "data", root / "output"
    from apflow import cli
    cli.ROOT = root
    c = TestClient(api.app)
    r = c.post("/api/pipeline/run", json={"name": "apitest", "scale": 0.1})
    assert r.status_code == 200, r.text
    return c


def test_health_and_datasets(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    names = [d["name"] for d in client.get("/api/datasets").json()]
    assert "apitest" in names


def test_summary_has_safety_gate(client):
    s = client.get("/api/summary", params={"dataset": "apitest"}).json()
    assert s["metrics"]["safety"]["blocked_invoices_marked_payment_ready"] == 0
    assert s["validation"]["passed"] is True
    assert s["reproducibility"]["identical"] is True


def test_invoice_filters(client):
    allr = client.get("/api/invoices", params={"dataset": "apitest", "limit": 500}).json()
    assert allr["total"] == 200
    ready = client.get("/api/invoices", params={"dataset": "apitest", "state": "PAYMENT_READY"}).json()
    assert ready["total"] == 140
    assert all(i["exceptions"] == "" for i in ready["items"])
    dup = client.get("/api/invoices", params={"dataset": "apitest", "queue": "AP_DUPLICATE_REVIEW"}).json()
    assert dup["total"] == 10


def test_invoice_detail_has_audit_trail_and_document(client):
    first = client.get("/api/invoices", params={"dataset": "apitest", "state": "EXCEPTION_ROUTED", "limit": 1}).json()
    iid = first["items"][0]["invoice_id"]
    d = client.get(f"/api/invoices/{iid}", params={"dataset": "apitest"}).json()
    assert d["exceptions"] and d["events"][0]["to_state"] == "RECEIVED"
    assert d["events"][-1]["to_state"] == "EXCEPTION_ROUTED"
    assert d["document"]["invoice_id"] == iid


def test_errors(client):
    assert client.get("/api/invoices/INV-XXX01-2026-999999", params={"dataset": "apitest"}).status_code == 404
    assert client.get("/api/summary", params={"dataset": "nope"}).status_code == 404
    assert client.get("/api/summary", params={"dataset": "../etc"}).status_code == 400
