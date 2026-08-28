from sqlalchemy import text


def get_processed_files(engine):
    with engine.begin() as conn:
        result = conn.execute(text("""
            SELECT file_name 
            FROM dw.etl_files_processed
        """))

        return set([row[0] for row in result])


def register_file(engine, file_name):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO dw.etl_files_processed (file_name)
            VALUES (:f)
        """), {
            "f": file_name
        })
