import argparse
import json
import os
import re
import tempfile
from pathlib import Path

import yaml
from sqlalchemy import text

from automation_platform.core.runner import AutomationRunner
from etl_platform.core.config import _load_yaml_file, load_config
from etl_platform.core.db.connection import get_engine
from etl_platform.migrations import run_migrations
from etl_platform.pipelines.pipeline_runner import run_pipeline
from etl_platform.validators import validate_config_full


CERT_DATABASE_PATTERN = re.compile(r"^ORBELION_[A-Z0-9_]+_CERT$")


class CertificationError(RuntimeError):
    pass


def validate_certification_database_name(name):
    if not CERT_DATABASE_PATTERN.fullmatch(name or ""):
        raise CertificationError(
            "Certification database must match ORBELION_<NAME>_CERT."
        )
    return name


def _database_admin_engine(config):
    admin_config = dict(config)
    admin_config["database"] = "master"
    return get_engine(admin_config)


def _execute_admin(engine, sql):
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(sql)


def _create_database(engine, database):
    exists = False
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM sys.databases WHERE name = :name"), {"name": database}
        ).fetchone() is not None
    if exists:
        raise CertificationError(f"Certification database already exists: {database}")
    _execute_admin(engine, f"CREATE DATABASE [{database}]")


def _drop_database(engine, database):
    _execute_admin(
        engine,
        f"IF DB_ID('{database}') IS NOT NULL BEGIN "
        f"ALTER DATABASE [{database}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
        f"DROP DATABASE [{database}]; END",
    )


def _table_counts(engine, schema):
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT t.name, SUM(p.rows) AS row_count
            FROM sys.tables t
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            JOIN sys.partitions p ON t.object_id = p.object_id AND p.index_id IN (0, 1)
            WHERE s.name = :schema
            GROUP BY t.name
        """), {"schema": schema})
        return {row[0]: int(row[1]) for row in rows}


def certify_client(
    config_path,
    client,
    database,
    automation_clients="config/automations/clients.example.yml",
    automation_jobs="config/automations/jobs.example.yml",
):
    validate_certification_database_name(database)
    validate_config_full(config_path, check_db=False, diagnostic=False)
    base_config = load_config(config_path)
    admin_engine = _database_admin_engine(base_config)
    temp_path = None
    created = False
    report = {"client": client, "database": database, "status": "FAILED"}
    try:
        _create_database(admin_engine, database)
        created = True
        raw = _load_yaml_file(config_path)
        raw.pop("__config_path__", None)
        raw.pop("config_dir", None)
        raw["database"] = database
        raw["process_name"] = f"{client}_certification"
        config_dir = os.path.dirname(os.path.abspath(config_path))
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", prefix="orbelion_cert_", dir=config_dir,
            encoding="utf-8", delete=False,
        )
        temp_path = handle.name
        with handle:
            yaml.safe_dump(raw, handle, sort_keys=False, allow_unicode=True)

        run_migrations(temp_path, client)
        run_pipeline(temp_path)
        cert_config = load_config(temp_path)
        cert_engine = get_engine(cert_config)
        first_counts = _table_counts(cert_engine, cert_config.get("schema", "dw"))
        cert_engine.dispose()

        run_pipeline(temp_path)
        cert_engine = get_engine(cert_config)
        second_counts = _table_counts(cert_engine, cert_config.get("schema", "dw"))
        cert_engine.dispose()

        protected = {
            name for name in first_counts
            if name.startswith("fact_") or name.startswith("dim_")
        }
        changed = {
            name: (first_counts.get(name), second_counts.get(name))
            for name in protected if first_counts.get(name) != second_counts.get(name)
        }
        if changed:
            raise CertificationError(f"Idempotency failed for tables: {sorted(changed)}")

        dry_run = AutomationRunner().run(
            "demo_client", "noop", dry_run=True,
            clients_config=automation_clients, jobs_config=automation_jobs,
        )
        if not dry_run.get("dry_run"):
            raise CertificationError("Automation dry-run contract failed.")

        report.update({
            "status": "PASSED",
            "first_counts": first_counts,
            "second_counts": second_counts,
            "automation_dry_run": dry_run,
        })
        return report
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        if created:
            _drop_database(admin_engine, database)
        admin_engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Certify a client on an isolated SQL Server database.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--execute", action="store_true", help="Required safety acknowledgement.")
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    if not args.execute:
        print("CLIENT CERTIFICATION FAILED: --execute is required")
        return 2
    try:
        report = certify_client(args.config, args.client, args.database)
    except Exception as exc:
        print(f"CLIENT CERTIFICATION FAILED: {type(exc).__name__}")
        return 3
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("CLIENT CERTIFICATION PASSED")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
