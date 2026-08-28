import argparse
import os
import re
import sys
from datetime import datetime

from sqlalchemy import text

from etl_platform.core.config import load_config
from etl_platform.core.db.connection import get_engine
from etl_platform.validators import ValidationError, validate_config_full


def split_batches(sql_text):
    pattern = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)
    return [batch.strip() for batch in pattern.split(sql_text) if batch.strip()]


def execute_sql_file(conn, file_path):
    with open(file_path, "r", encoding="utf-8-sig") as stream:
        sql_text = stream.read()
    for batch in split_batches(sql_text):
        conn.exec_driver_sql(batch)


def _migration_directories(root_dir, config, client):
    directories = []
    source_types = {source.get("type") for source in config.get("sources", [])}
    if config.get("analytical_contract_version"):
        directories.append(("analytics", os.path.join(root_dir, "ddl", "migrations", "analytics")))
    if "odoo" in source_types:
        directories.append(("odoo", os.path.join(root_dir, "ddl", "migrations", "odoo")))
    directories.append((client, os.path.join(root_dir, "ddl", "migrations", client)))
    return directories


def _validate_migration_directories(directories):
    for scope, path in directories:
        if not os.path.isdir(path):
            raise ValueError(f"Migration directory does not exist for '{scope}': {path}")
        if not any(name.endswith(".sql") for name in os.listdir(path)):
            raise ValueError(f"No SQL migrations found for '{scope}'.")


def _record_run_start(engine):
    with engine.begin() as conn:
        result = conn.execute(text("""
            INSERT INTO dw.etl_runs (process_name, start_time, status)
            OUTPUT INSERTED.run_id
            VALUES (:process, :start, 'RUNNING')
        """), {"process": "migrations", "start": datetime.now()})
        return result.scalar()


def _record_run_end(engine, run_id, status, error_message=None):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE dw.etl_runs
            SET end_time = :end, status = :status, error_message = :error
            WHERE run_id = :run_id
        """), {
            "end": datetime.now(),
            "status": status,
            "error": error_message,
            "run_id": run_id,
        })


def run_migrations(config_path, client):
    config = load_config(config_path)
    engine = get_engine(config)
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    base_path = os.path.join(root_dir, "ddl", "base")
    if not os.path.isdir(base_path):
        raise ValueError(f"Base DDL directory does not exist: {base_path}")

    directories = _migration_directories(root_dir, config, client)
    _validate_migration_directories(directories)

    print(f"\nClient: {client}")
    print(f"Database: {config['database']}")
    print("Migration scopes: " + ", ".join(scope for scope, _ in directories) + "\n")

    with engine.begin() as conn:
        for file_name in sorted(os.listdir(base_path)):
            if file_name.endswith(".sql"):
                print(f"Base: {file_name}")
                execute_sql_file(conn, os.path.join(base_path, file_name))

    run_id = _record_run_start(engine)
    try:
        with engine.begin() as conn:
            for scope, path in directories:
                for file_name in sorted(os.listdir(path)):
                    if not file_name.endswith(".sql"):
                        continue
                    migration_id = f"{scope}/{file_name}"
                    exists = conn.execute(text("""
                        SELECT 1 FROM dw.etl_files_processed WHERE file_name = :file
                    """), {"file": migration_id}).fetchone()
                    if exists:
                        print(f"SKIP: {migration_id}")
                        continue
                    print(f"Executing: {migration_id}")
                    execute_sql_file(conn, os.path.join(path, file_name))
                    conn.execute(text("""
                        INSERT INTO dw.etl_files_processed (file_name) VALUES (:file)
                    """), {"file": migration_id})
        _record_run_end(engine, run_id, "SUCCESS")
    except Exception as exc:
        sanitized_error = type(exc).__name__
        _record_run_end(engine, run_id, "FAILED", sanitized_error)
        print(f"\nMIGRATIONS FAILED: {sanitized_error}")
        raise

    print("\nMIGRATIONS COMPLETED\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run versioned ETL migrations.")
    parser.add_argument("config", help="Path to YAML config file")
    parser.add_argument("client", help="Client code")
    parser.add_argument("--no-db", dest="check_db", action="store_false", help="Static pre-validation")
    args = parser.parse_args(argv)
    try:
        validate_config_full(args.config, check_db=args.check_db)
        run_migrations(args.config, args.client)
    except ValidationError as exc:
        print(f"CONFIG VALIDATION FAILED: {exc}")
        return 2
    except Exception as exc:
        print(f"MIGRATION COMMAND FAILED: {type(exc).__name__}")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
