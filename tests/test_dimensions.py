from pathlib import Path

from etl_platform.core.db.dimensions import merge_dimension


ROOT = Path(__file__).resolve().parent.parent


def test_base_migration_creates_and_populates_standard_date_dimension():
    migration = (
        ROOT / "ddl" / "base" / "V005_date_dimension.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE dw.dim_fecha" in migration
    assert "CREATE UNIQUE INDEX ux_dim_fecha_fecha" in migration
    assert "MERGE dw.dim_fecha WITH (HOLDLOCK)" in migration
    assert "WHEN NOT MATCHED THEN INSERT" in migration
    assert "DATEPART(QUARTER, fecha)" in migration
    assert "SYSUTCDATETIME()" in migration


def test_date_dimension_migration_is_additive_and_non_destructive():
    migration = (
        ROOT / "ddl" / "base" / "V005_date_dimension.sql"
    ).read_text(encoding="utf-8").lower()

    assert "if object_id('dw.dim_fecha', 'u') is null" in migration
    assert "drop " not in migration
    assert "truncate " not in migration
    assert "delete " not in migration


class _Connection:
    def __init__(self, statements):
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def exec_driver_sql(self, sql):
        self.statements.append(sql)


class _Engine:
    def __init__(self):
        self.statements = []

    def begin(self):
        return _Connection(self.statements)


def test_dimension_merge_supports_staging_to_dimension_column_aliases():
    engine = _Engine()

    merge_dimension(
        engine,
        "dw.dim_producto_servicio",
        "dw.stg_ventas",
        "producto_code",
        ["producto_code", "nombre", "categoria"],
        {"nombre": "producto_nombre"},
    )

    sql = engine.statements[0]
    assert "MAX(producto_nombre) AS nombre" in sql
    assert "MAX(categoria) AS categoria" in sql
    assert "GROUP BY producto_code" in sql
