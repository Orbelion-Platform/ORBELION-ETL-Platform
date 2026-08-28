import pandas as pd
from sqlalchemy import create_engine


def extract_data(source_config, watermark=None):
    connection_string = source_config.get("connection_string")
    query = source_config.get("query")

    if not connection_string or not query:
        raise ValueError("Database source requiere connection_string y query")

    engine = create_engine(connection_string)
    df = pd.read_sql(query, engine)

    if df.empty:
        return df

    df["__source"] = source_config.get("name", "database")
    return df
