import pandas as pd
import pytest
from datetime import datetime

from etl_platform.core.db.staging import (
    StagingContractError,
    load_staging,
    validate_staging_values,
)


def _contract(**overrides):
    base = {
        "data_type": "nvarchar",
        "max_length": 100,
        "precision": None,
        "scale": None,
        "nullable": True,
    }
    base.update(overrides)
    return base


def test_staging_contract_reports_oversized_column_without_value_contents():
    df = pd.DataFrame({"nombre": ["x" * 101]})

    with pytest.raises(StagingContractError) as exc_info:
        validate_staging_values(
            df,
            {"nombre": _contract()},
            "dw",
            "stg_ventas",
            ["nombre"],
        )

    message = str(exc_info.value)
    assert "dw.stg_ventas.nombre" in message
    assert "maximum=100 observed=101" in message
    assert "x" * 20 not in message


def test_staging_contract_reports_nulls_for_legacy_not_null_column():
    df = pd.DataFrame({"venta_id": ["SO-1", pd.NA]})

    with pytest.raises(StagingContractError, match="rows_with_null=1"):
        validate_staging_values(
            df,
            {"venta_id": _contract(nullable=False)},
            "dw",
            "stg_ventas",
            ["venta_id"],
        )


def test_staging_contract_reports_numeric_overflow():
    df = pd.DataFrame({"total": [100000.0]})

    with pytest.raises(StagingContractError, match="precision=9 scale=4"):
        validate_staging_values(
            df,
            {
                "total": _contract(
                    data_type="decimal",
                    max_length=None,
                    precision=9,
                    scale=4,
                )
            },
            "dw",
            "stg_ventas",
            ["total"],
        )


def test_staging_contract_rejects_datetime_for_sql_date_before_truncate():
    df = pd.DataFrame({"fecha": [datetime(2026, 7, 14, 0, 46, 36)]})

    with pytest.raises(StagingContractError, match="rows_with_time=1"):
        validate_staging_values(
            df,
            {"fecha": _contract(data_type="date", max_length=None)},
            "dw",
            "stg_ventas",
            ["fecha"],
        )


class _Transaction:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("begin")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.events.append("rollback" if exc_type else "commit")
        return False

    def execute(self, statement, params=None):
        sql = str(statement)
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            return [
                ("venta_id", "nvarchar", 100, None, None, "YES"),
            ]
        self.events.append(sql.strip())
        return []


class _Engine:
    def __init__(self):
        self.events = []

    def begin(self):
        return _Transaction(self.events)


def test_staging_truncate_and_insert_share_one_transaction(monkeypatch):
    engine = _Engine()
    df = pd.DataFrame({"venta_id": ["SO-1"]})

    def fake_to_sql(self, *, name, con, schema, if_exists, index):
        assert con is not engine
        engine.events.append("insert")

    monkeypatch.setattr(pd.DataFrame, "to_sql", fake_to_sql)

    load_staging(
        engine,
        df,
        {"schema": "dw", "staging_table": "stg_ventas"},
    )

    assert engine.events[-4:] == ["begin", "TRUNCATE TABLE dw.stg_ventas", "insert", "commit"]


def test_failed_staging_insert_rolls_back_truncate(monkeypatch):
    engine = _Engine()
    df = pd.DataFrame({"venta_id": ["SO-1"]})

    def fail_to_sql(self, **kwargs):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(pd.DataFrame, "to_sql", fail_to_sql)

    with pytest.raises(RuntimeError, match="insert failed"):
        load_staging(
            engine,
            df,
            {"schema": "dw", "staging_table": "stg_ventas"},
        )

    assert engine.events[-3:] == [
        "begin",
        "TRUNCATE TABLE dw.stg_ventas",
        "rollback",
    ]
