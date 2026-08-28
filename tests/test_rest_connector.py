import logging

import pytest

from etl_platform.core.extract.connectors import api_connector


class DummyResponse:
    def __init__(self, payload, status_code=200, url="https://api.example.com/items"):
        self.payload = payload
        self.status_code = status_code
        self.url = url
        self.text = str(payload)

    def json(self):
        return self.payload


class DummySession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, params=None, timeout=None):
        self.calls.append({
            "method": method,
            "url": url,
            "headers": headers or {},
            "params": params or {},
            "timeout": timeout,
        })
        return self.responses.pop(0)


def test_rest_connector_applies_bearer_auth_incremental_params_and_timeout(monkeypatch, caplog):
    monkeypatch.setenv("API_TOKEN", "super-secret-token")
    session = DummySession([DummyResponse({"data": [{"id": 1, "updated_at": "2026-01-01"}]})])

    with caplog.at_level(logging.INFO):
        df = api_connector.extract_data(
            {
                "name": "orders_api",
                "type": "rest",
                "url": "https://api.example.com/items",
                "data_key": "data",
                "timeout": 12,
                "params": {"status": "posted"},
                "auth": {"type": "bearer", "token_env": "API_TOKEN"},
                "incremental_param": "updated_after",
                "session": session,
            },
            watermark="2026-01-01T00:00:00",
        )

    assert df["id"].tolist() == [1]
    assert session.calls[0]["timeout"] == 12
    assert session.calls[0]["headers"]["Authorization"] == "Bearer super-secret-token"
    assert session.calls[0]["params"]["updated_after"] == "2026-01-01T00:00:00"
    assert "super-secret-token" not in caplog.text


def test_rest_connector_applies_api_key_in_query(monkeypatch):
    monkeypatch.setenv("API_KEY", "abc123")
    session = DummySession([DummyResponse([{"id": 1}])])

    api_connector.extract_data(
        {
            "type": "rest",
            "url": "https://api.example.com/items",
            "auth": {"type": "api_key", "key_env": "API_KEY", "name": "api_key", "in": "query"},
            "session": session,
        }
    )

    assert session.calls[0]["params"]["api_key"] == "abc123"


def test_rest_connector_retries_retryable_status():
    session = DummySession([
        DummyResponse({"error": "temporary"}, status_code=500),
        DummyResponse([{"id": 2}], status_code=200),
    ])

    df = api_connector.extract_data(
        {
            "type": "rest",
            "url": "https://api.example.com/items",
            "retry": {"attempts": 2, "backoff_factor": 0, "status_codes": [500]},
            "session": session,
        }
    )

    assert len(session.calls) == 2
    assert df["id"].tolist() == [2]


def test_rest_connector_paginates_until_empty_page():
    session = DummySession([
        DummyResponse({"data": [{"id": 1}]}),
        DummyResponse({"data": [{"id": 2}]}),
        DummyResponse({"data": []}),
    ])

    df = api_connector.extract_data(
        {
            "type": "rest",
            "url": "https://api.example.com/items",
            "data_key": "data",
            "pagination": {"type": "page", "page_param": "page", "max_pages": 5},
            "session": session,
        }
    )

    assert df["id"].tolist() == [1, 2]
    assert [call["params"]["page"] for call in session.calls] == [1, 2, 3]


def test_rest_connector_raises_structured_http_error():
    session = DummySession([DummyResponse({"error": "unauthorized"}, status_code=401)])

    with pytest.raises(api_connector.RestConnectorError, match="HTTP 401"):
        api_connector.extract_data(
            {
                "type": "rest",
                "url": "https://api.example.com/items",
                "retry": {"attempts": 1},
                "session": session,
            }
        )
