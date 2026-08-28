from datetime import datetime
from sqlalchemy import text


def start_run(engine, process_name):
    with engine.begin() as conn:
        result = conn.execute(text("""
            INSERT INTO dw.etl_runs (process_name, start_time, status)
            OUTPUT INSERTED.run_id
            VALUES (:p, :s, 'RUNNING')
        """), {
            "p": process_name,
            "s": datetime.now()
        })
        return result.scalar()


def end_run(engine, run_id, status, records_processed, error_message=None):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE dw.etl_runs
            SET end_time = :e,
                status = :s,
                records_processed = :r,
                error_message = :error
            WHERE run_id = :id
        """), {
            "e": datetime.now(),
            "s": status,
            "r": records_processed,
            "error": error_message,
            "id": run_id
        })


def _watermark_identity(process_name, source_name=None, entity_name=None, endpoint=None):
    return {
        "process_name": process_name,
        "source_name": source_name or "__default__",
        "entity_name": entity_name or "__default__",
        "endpoint": endpoint or "__default__",
    }


def build_watermark_identity(process_name, source_config):
    return _watermark_identity(
        process_name,
        source_config.get("name"),
        source_config.get("entity") or source_config.get("object"),
        source_config.get("endpoint") or source_config.get("url") or source_config.get("path"),
    )


def get_watermark(engine, process_name, source_name=None, entity_name=None, endpoint=None):
    identity = _watermark_identity(process_name, source_name, entity_name, endpoint)
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT last_value 
            FROM dw.etl_watermark
            WHERE process_name = :process_name
              AND source_name = :source_name
              AND entity_name = :entity_name
              AND endpoint = :endpoint
        """), identity).fetchone()

        return row[0] if row and row[0] is not None else None


def update_watermark(engine, process_name, value, source_name=None, entity_name=None, endpoint=None):

    if value is None:
        return

    identity = _watermark_identity(process_name, source_name, entity_name, endpoint)
    params = {**identity, "last_value": str(value), "updated_at": datetime.now()}

    with engine.begin() as conn:
        conn.execute(text("""
            MERGE dw.etl_watermark AS t
            USING (
                SELECT
                    :process_name AS process_name,
                    :source_name AS source_name,
                    :entity_name AS entity_name,
                    :endpoint AS endpoint,
                    :last_value AS last_value,
                    :updated_at AS updated_at
            ) AS s
            ON t.process_name = s.process_name
               AND t.source_name = s.source_name
               AND t.entity_name = s.entity_name
               AND t.endpoint = s.endpoint
            WHEN MATCHED THEN 
                UPDATE SET last_value = s.last_value,
                           updated_at = s.updated_at
            WHEN NOT MATCHED THEN 
                INSERT (process_name, source_name, entity_name, endpoint, last_value, updated_at)
                VALUES (s.process_name, s.source_name, s.entity_name, s.endpoint, s.last_value, s.updated_at);
        """), params)
