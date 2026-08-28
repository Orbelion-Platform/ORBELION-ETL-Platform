from etl_platform.core.db import control


class ScalarResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.engine.executions.append((str(sql), params or {}))
        return ScalarResult(self.engine.row)


class FakeEngine:
    def __init__(self, row=None):
        self.row = row
        self.executions = []

    def begin(self):
        return FakeConnection(self)


def test_build_watermark_identity_uses_source_entity_endpoint():
    identity = control.build_watermark_identity(
        "daily_sync",
        {
            "name": "orders",
            "entity": "sale.order",
            "url": "https://api.example.com/orders",
        },
    )

    assert identity == {
        "process_name": "daily_sync",
        "source_name": "orders",
        "entity_name": "sale.order",
        "endpoint": "https://api.example.com/orders",
    }


def test_get_watermark_filters_by_full_identity():
    engine = FakeEngine(row=("2026-01-01T00:00:00",))

    value = control.get_watermark(
        engine,
        "daily_sync",
        source_name="orders",
        entity_name="sale.order",
        endpoint="/orders",
    )

    assert value == "2026-01-01T00:00:00"
    assert engine.executions[0][1]["process_name"] == "daily_sync"
    assert engine.executions[0][1]["source_name"] == "orders"
    assert engine.executions[0][1]["entity_name"] == "sale.order"
    assert engine.executions[0][1]["endpoint"] == "/orders"


def test_update_watermark_merges_by_full_identity():
    engine = FakeEngine()

    control.update_watermark(
        engine,
        "daily_sync",
        "2026-01-02T00:00:00",
        source_name="invoices",
        entity_name="account.move",
        endpoint="/invoices",
    )

    sql, params = engine.executions[0]
    assert "source_name" in sql
    assert params["process_name"] == "daily_sync"
    assert params["source_name"] == "invoices"
    assert params["entity_name"] == "account.move"
    assert params["endpoint"] == "/invoices"
    assert params["last_value"] == "2026-01-02T00:00:00"
