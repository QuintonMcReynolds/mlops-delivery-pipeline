from app import main


def test_health_and_ready(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["model_version"] == "test"


def test_not_ready_without_model(client):
    saved = main.State.model
    main.State.model = None
    try:
        assert client.get("/readyz").status_code == 503
        assert client.get("/healthz").status_code == 200
    finally:
        main.State.model = saved


def test_predict(client, sample_rows):
    r = client.post("/predict", json={"rows": sample_rows})
    assert r.status_code == 200
    body = r.json()
    assert body["model_version"] == "test"
    assert len(body["predictions"]) == 3
    for p in body["predictions"]:
        assert p["label"] in ("malignant", "benign")
        assert 0 <= p["probability_benign"] <= 1
        assert p["out_of_distribution"] is False
    assert r.headers["x-model-version"] == "test"
    assert "x-request-id" in r.headers


def test_known_malignant_case(client, sample_rows):
    # The first row of the dataset is a malignant tumour.
    r = client.post("/predict", json={"rows": sample_rows[:1]})
    assert r.json()["predictions"][0]["label"] == "malignant"


def test_flags_out_of_distribution(client, sample_rows):
    weird = [v * 1000 for v in sample_rows[0]]
    r = client.post("/predict", json={"rows": [weird]})
    assert r.json()["predictions"][0]["out_of_distribution"] is True


def test_rejects_wrong_shape(client):
    assert client.post("/predict", json={"rows": [[1.0, 2.0]]}).status_code == 422
    assert client.post("/predict", json={"rows": []}).status_code == 422
    assert client.post("/predict", json={}).status_code == 422


def test_request_id_is_echoed(client):
    r = client.get("/version", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"


def test_metrics_exposed(client, sample_rows):
    client.post("/predict", json={"rows": sample_rows})
    text = client.get("/metrics").text
    assert "api_requests_total" in text
    assert "model_predictions_total" in text


def test_stays_up_but_not_ready_when_model_missing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "MODEL_DIR", tmp_path)
    main.State.model, main.State.meta = None, {}
    with TestClient(main.app) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/readyz").status_code == 503
        assert c.post("/predict", json={"rows": [[0.0] * 30]}).status_code == 503
