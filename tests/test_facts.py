from pathlib import Path

from etl_platform.migrations import _migration_directories
from etl_platform.validators import _migration_paths_for_config


ROOT = Path(__file__).resolve().parent.parent


def test_standard_analytical_fact_migration_preserves_v1_and_creates_v2_grains():
    migration = (
        ROOT / "ddl" / "migrations" / "analytics" /
        "V001__standard_analytical_fact_contract.sql"
    ).read_text(encoding="utf-8")

    for fact in ("ventas", "compras", "gastos", "inventario"):
        assert f"dw.fact_{fact}_legacy" in migration
        assert f"CREATE TABLE dw.fact_{fact}" in migration

    for staging in ("ventas", "compras", "gastos", "inventario"):
        assert f"CREATE TABLE dw.stg_{staging}" in migration

    for dimension in ("cliente", "producto_servicio", "proveedor", "gasto"):
        assert f"CREATE TABLE dw.dim_{dimension}" in migration

    assert "venta_linea_id" in migration
    assert "compra_linea_id" in migration
    assert "inventario_movimiento_id" in migration
    assert "fecha_key INT" in migration
    assert "producto_key INT" in migration
    assert "END;\nELSE" not in migration


def test_standard_analytical_fact_migration_does_not_delete_business_data():
    migration = (
        ROOT / "ddl" / "migrations" / "analytics" /
        "V001__standard_analytical_fact_contract.sql"
    ).read_text(encoding="utf-8").lower()

    assert "drop table" not in migration
    assert "truncate table" not in migration
    assert "delete from" not in migration


def test_v2_legacy_backfill_is_idempotent_reconciled_and_non_destructive():
    migration = (
        ROOT / "ddl" / "migrations" / "analytics" /
        "V003__backfill_legacy_facts_v2.sql"
    ).read_text(encoding="utf-8")
    lowered = migration.lower()

    assert "merge dw.fact_gastos with (holdlock)" in lowered
    assert "on target.gasto_id = source.gasto_id" in lowered
    assert "merge dw.fact_inventario with (holdlock)" in lowered
    assert "legacy_quant:" in lowered
    assert "hashbytes(" in lowered
    assert "legacy_no_clasificado" in lowered
    assert "saldo_inicial_legacy" in lowered
    assert "@gastos_v2_before_count" in lowered
    assert "@gastos_v2_after_sum" in lowered
    assert "@inventario_v2_before_count" in lowered
    assert "@inventario_v2_after_sum" in lowered
    assert "orphan proveedor surrogate keys" in lowered
    assert "orphan producto surrogate keys" in lowered
    assert "drop table" not in lowered
    assert "truncate table" not in lowered
    assert "delete from" not in lowered


def test_v2_reconciliation_script_is_read_only_and_covers_required_metrics():
    audit = (
        ROOT / "ddl" / "audits" / "analytical_v2_reconciliation.sql"
    ).read_text(encoding="utf-8").lower()

    assert "count_big" in audit
    assert "sum(convert(decimal(38,4), importe))" in audit
    assert "sum(convert(decimal(38,4), valor))" in audit
    assert "group by tipo_movimiento" in audit
    assert "legacy_keys_missing_in_v2" in audit
    assert "legacy_snapshots_missing_in_v2" in audit
    assert "native_rows_with_quantity_without_valuation" in audit
    assert "native_inventory_value_sum" in audit
    assert "insert into dw." not in audit
    assert "update dw." not in audit
    assert "delete from dw." not in audit
    assert "drop table dw." not in audit


def test_v2_inventory_valuation_repair_is_idempotent_and_preserves_keys():
    migration = (
        ROOT / "ddl" / "migrations" / "analytics" /
        "V004__repair_inventory_movement_valuation.sql"
    ).read_text(encoding="utf-8").lower()

    assert "insert into @product_cost" in migration
    assert "sum(convert(decimal(38,10), abs(legacy.valor)))" in migration
    assert "update target" in migration
    assert "legacy_quant:%" in migration
    assert "fact_id_before <> fact_id_after" in migration
    assert "@after_count <> @before_count" in migration
    assert "@after_sum <> @before_sum + @repair_delta" in migration
    assert "drop table" not in migration
    assert "truncate table" not in migration
    assert "delete from" not in migration


def test_staging_alignment_hotfix_repairs_existing_warehouses_safely():
    migration = (
        ROOT / "ddl" / "migrations" / "analytics" /
        "V002__align_existing_staging_contract.sql"
    ).read_text(encoding="utf-8")
    lowered = migration.lower()

    assert "alter column cliente_id nvarchar(100) null" in lowered
    assert "alter column nombre nvarchar(255) null" in lowered
    assert "alter column total decimal(18,4) null" in lowered
    assert "alter column fecha date null" in lowered
    assert "alter column producto_code nvarchar(150) null" in lowered
    assert "alter column cliente_id nvarchar(100) not null" in lowered
    assert "alter table dw.dim_cliente alter column nombre nvarchar(255) null" in lowered
    assert "drop table" not in lowered
    assert "truncate table" not in lowered
    assert "delete from" not in lowered


def test_analytical_contract_scope_is_source_agnostic():
    directories = _migration_directories(
        str(ROOT),
        {"analytical_contract_version": "2.0.0", "sources": [{"type": "rest"}]},
        "new_client",
    )

    assert directories[0][0] == "analytics"
    assert directories[0][1].endswith(str(Path("ddl") / "migrations" / "analytics"))
    assert directories[1][0] == "new_client"


def test_odoo_adapter_migration_scope_is_applied_before_client_scope():
    directories = _migration_directories(
        str(ROOT),
        {"analytical_contract_version": "2.0.0", "sources": [{"type": "odoo"}]},
        "new_client",
    )

    assert [scope for scope, _ in directories] == ["analytics", "odoo", "new_client"]


def test_validator_reads_the_same_shared_analytics_scope():
    paths = _migration_paths_for_config(
        {"analytical_contract_version": "2.0.0", "sources": [{"type": "rest"}]},
        str(ROOT),
        "new_client",
    )

    assert paths[0].endswith(str(Path("ddl") / "migrations" / "analytics"))
