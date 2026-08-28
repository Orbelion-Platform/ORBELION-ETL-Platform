import os
from pathlib import Path

import pandas as pd

from etl_platform.core.db.control import (
    build_watermark_identity,
    get_watermark,
    update_watermark,
)
from etl_platform.core.db.ddl_manager import apply_base_migrations, create_financial_model
from etl_platform.core.db.dimensions import load_dimensions
from etl_platform.core.db.facts import load_facts
from etl_platform.core.db.file_control import get_processed_files, register_file
from etl_platform.core.db.staging import load_staging
from etl_platform.core.extract.extract_dynamic import extract_data
from etl_platform.core.transform.transform_basic import apply_transforms


FILE_EXTENSIONS = {
    "csv": {".csv"},
    "excel": {".xls", ".xlsx", ".xlsm"},
}


def list_source_files(folder, source_type):
    extensions = FILE_EXTENSIONS.get(source_type)
    files = []

    for file_name in os.listdir(folder):
        full_path = os.path.join(folder, file_name)

        if not os.path.isfile(full_path):
            continue

        if extensions and Path(file_name).suffix.lower() not in extensions:
            continue

        files.append(file_name)

    return sorted(files)


def prepare_environment(context):
    context.current_step = "prepare_environment"
    ddl_base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "ddl", "base")
    )
    apply_base_migrations(context.engine, ddl_base_dir)


def prepare_data_model(context):
    context.current_step = "prepare_data_model"
    create_financial_model(context.engine, context.config.get("schema", "dw"))


def get_source_watermark(context, source_config):
    if context.mode not in ["incremental", "hybrid"]:
        return None

    identity = build_watermark_identity(context.process_name, source_config)
    return get_watermark(context.engine, **identity)


def collect_watermark_update(context, df, source_config):
    incremental_column = context.config.get("incremental_column")
    if not incremental_column or df.empty or incremental_column not in df.columns:
        return None

    max_value = df[incremental_column].max()
    if pd.isna(max_value):
        return None

    identity = build_watermark_identity(context.process_name, source_config)
    return {**identity, "value": max_value}


def select_files_for_mode(files, processed_files, mode):
    if mode == "files":
        return [f for f in files if f not in processed_files]
    if mode == "incremental":
        return files
    if mode == "hybrid":
        return [f for f in files if f not in processed_files]
    raise ValueError(f"Modo invÃ¡lido: {mode}")


def _append_extracted_frame(context, df, source_config):
    if df.empty:
        return

    context.extracted_frames.append(df)
    update_payload = collect_watermark_update(context, df, source_config)
    if update_payload:
        context.watermark_updates.append(update_payload)


def extract_file_source(context, source_config):
    folder = source_config["path"]

    if not os.path.isdir(folder):
        raise ValueError(f"Path debe ser carpeta: {folder}")

    files = list_source_files(folder, source_config["type"])
    processed_files = get_processed_files(context.engine)
    files_to_process = select_files_for_mode(files, processed_files, context.mode)

    for file_name in files_to_process:
        full_path = os.path.join(folder, file_name)
        temp_source = {
            "type": source_config["type"],
            "name": source_config.get("name"),
            "path": full_path,
            "entity": source_config.get("entity"),
            "endpoint": full_path,
            "sheet_name": source_config.get("sheet_name"),
            "incremental_column": context.config.get("incremental_column"),
        }

        watermark = get_source_watermark(context, temp_source)
        df = extract_data(temp_source, watermark)

        if context.mode in ["files", "hybrid"]:
            context.files_loaded.add(file_name)

        _append_extracted_frame(context, df, temp_source)


def extract_remote_source(context, source_config):
    source_config["incremental_column"] = context.config.get("incremental_column")
    watermark = get_source_watermark(context, source_config)
    df = extract_data(source_config, watermark)
    _append_extracted_frame(context, df, source_config)


def extract_sources(context):
    context.current_step = "extraction"

    for source_config in context.config["sources"]:
        source_type = source_config["type"]

        if source_type in {"csv", "excel"}:
            extract_file_source(context, source_config)
        elif source_type in {"api", "rest", "database", "odoo"}:
            extract_remote_source(context, source_config)
        else:
            raise ValueError(f"Fuente no soportada: {source_type}")


def transform_data(context):
    context.current_step = "transformation"
    df = pd.concat(context.extracted_frames, ignore_index=True)
    context.transformed_df = apply_transforms(df, context.config)
    return context.transformed_df


def load_staging_step(context):
    context.current_step = "staging_load"
    load_staging(context.engine, context.transformed_df, context.config)


def load_dimensions_step(context):
    context.current_step = "dimension_load"
    load_dimensions(context.engine, context.config)


def load_facts_step(context):
    context.current_step = "fact_load"
    load_facts(context.engine, context.config)


def register_processed_files(context):
    context.current_step = "file_control"
    for file_name in sorted(context.files_loaded):
        register_file(context.engine, file_name)


def update_watermarks(context):
    context.current_step = "watermark_update"
    for item in context.watermark_updates:
        update_watermark(context.engine, **item)

