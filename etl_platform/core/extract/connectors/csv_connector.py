import os
from pathlib import Path

import pandas as pd


CSV_EXTENSIONS = {".csv"}


def _resolve_paths(base_path):
    if os.path.isdir(base_path):
        return sorted(
            os.path.join(base_path, filename)
            for filename in os.listdir(base_path)
            if Path(filename).suffix.lower() in CSV_EXTENSIONS
        )
    return [base_path]


def extract_data(source_config, watermark=None):
    base_path = source_config["path"]
    paths = _resolve_paths(base_path)
    source_name = source_config.get("name") or "csv"

    if not paths:
        return pd.DataFrame()

    dataframes = []
    for path in paths:
        df = pd.read_csv(path)
        df["__source_file"] = os.path.basename(path)
        df["__source"] = source_name
        dataframes.append(df)

    return pd.concat(dataframes, ignore_index=True)
