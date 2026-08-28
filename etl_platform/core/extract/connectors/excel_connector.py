import os
from pathlib import Path

import pandas as pd


EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}


def _resolve_paths(base_path):
    if os.path.isdir(base_path):
        return sorted(
            os.path.join(base_path, filename)
            for filename in os.listdir(base_path)
            if Path(filename).suffix.lower() in EXCEL_EXTENSIONS
        )
    return [base_path]


def extract_data(source_config, watermark=None):
    base_path = source_config["path"]
    paths = _resolve_paths(base_path)
    source_name = source_config.get("name") or "excel"

    if not paths:
        return pd.DataFrame()

    dataframes = []
    for path in paths:
        df = pd.read_excel(path, sheet_name=source_config.get("sheet_name", 0))
        df["__source_file"] = os.path.basename(path)
        df["__source"] = source_name
        dataframes.append(df)

    return pd.concat(dataframes, ignore_index=True)
