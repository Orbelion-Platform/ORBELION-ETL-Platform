import pandas as pd

from etl_platform.core.extract.connectors import get_connector


def extract_data(source_config, watermark=None):
    source_type = source_config.get("type")
    if not source_type:
        raise ValueError("El source_config debe incluir 'type'.")

    connector = get_connector(source_type)
    df = connector(source_config, watermark)

    if df is None:
        return pd.DataFrame()

    if not isinstance(df, pd.DataFrame):
        raise TypeError("El conector debe devolver un pandas DataFrame.")

    if df.empty:
        return df

    df.columns = df.columns.str.strip().str.lower()
    if "__source" not in df.columns:
        df["__source"] = source_type

    incremental_column = source_config.get("incremental_column")
    if watermark is not None and incremental_column and incremental_column in df.columns:
        df[incremental_column] = pd.to_datetime(df[incremental_column], errors="coerce")
        df = df[df[incremental_column] > watermark]

    return df
