import os
from pathlib import Path

import pandas as pd
import pytest

from etl_platform.core.extract.connectors import get_connector
from etl_platform.core.extract.extract_dynamic import extract_data
from etl_platform.core.extract.connectors import api_connector


class DummyResponse:
    def __init__(self, json_data, status_code=200, url="https://example.com"):
        self._json_data = json_data
        self.status_code = status_code
        self.url = url
        self.text = str(json_data)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP Error")

    def json(self):
        return self._json_data


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


def test_csv_connector_reads_csv(tmp_path):
    file_path = tmp_path / "data.csv"
    file_path.write_text("id,name\n1,A\n2,B\n", encoding="utf-8")

    connector = get_connector("csv")
    df = connector({"type": "csv", "path": str(file_path)})

    assert df.shape == (2, 4)
    assert df["__source_file"].tolist() == ["data.csv", "data.csv"]
    assert list(df.columns) == ["id", "name", "__source_file", "__source"]


def test_extract_dynamic_dispatches_to_csv(tmp_path):
    file_path = tmp_path / "data.csv"
    file_path.write_text("id,name\n1,A\n", encoding="utf-8")

    df = extract_data({"type": "csv", "path": str(file_path)})
    assert df["id"].tolist() == [1]
    assert df["__source_file"].iloc[0] == "data.csv"


def test_api_connector_uses_data_key(monkeypatch):
    session = DummySession([DummyResponse({"data": [{"id": 1}]})])
    df = api_connector.extract_data({
        "type": "api",
        "url": "https://example.com",
        "data_key": "data",
        "session": session,
    })

    assert df.to_dict(orient="records") == [{"id": 1, "__source": "api"}]


def test_api_connector_propagates_http_error(monkeypatch):
    session = DummySession([DummyResponse({"error": "not found"}, status_code=404)])
    with pytest.raises(api_connector.RestConnectorError, match="HTTP 404"):
        api_connector.extract_data({"type": "api", "url": "https://example.com", "session": session})
