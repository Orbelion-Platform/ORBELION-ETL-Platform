import os
import re

import pandas as pd
from etl_platform.core.metadata.metadata_loader import load_all

CURRENCY_PATTERN = re.compile(r"[^\d\-\.,]")


def normalize_columns(df):
    df.columns = df.columns.str.strip().str.lower()
    return df


def _get_client_name(config):
    config_path = config.get("__config_path__")
    if not config_path:
        return None
    return os.path.basename(os.path.dirname(os.path.abspath(config_path)))


def _resolve_metadata_root(config):
    return os.path.abspath(
        config.get("metadata_root")
        or os.path.join(os.path.dirname(__file__), "..", "..", "..", "metadata")
    )


def _load_metadata(config):
    metadata_root = _resolve_metadata_root(config)
    client = config.get("client") or _get_client_name(config)
    return load_all(metadata_root, client)


def _normalize_string_series(series, rules):
    if series.dtype.name == "category":
        series = series.astype(str)

    output = series.astype(str)
    if rules.get("trim", True):
        output = output.str.strip()
    if rules.get("collapse_spaces", True):
        output = output.str.replace(r"\s+", " ", regex=True)
    if rules.get("lower", False):
        output = output.str.lower()
    if rules.get("upper", False):
        output = output.str.upper()

    return output.replace({"nan": pd.NA, "None": pd.NA, "none": pd.NA})


def _normalize_amount_series(series, rules):
    output = series.astype(str).fillna("")
    if rules.get("remove_currency_symbols", True):
        output = output.str.replace(CURRENCY_PATTERN, "", regex=True)

    thousand_sep = rules.get("thousand_separator")
    decimal_sep = rules.get("decimal_separator")

    if thousand_sep:
        output = output.str.replace(re.escape(thousand_sep), "", regex=True)
    if decimal_sep and decimal_sep != ".":
        output = output.str.replace(re.escape(decimal_sep), ".", regex=True)

    return pd.to_numeric(output, errors="coerce")


def _normalize_date_series(series, formats=None):
    if formats:
        result = pd.Series(pd.NaT, index=series.index)
        for fmt in formats:
            parsed = pd.to_datetime(series, format=fmt, errors="coerce")
            result = result.fillna(parsed)
        return result

    return pd.to_datetime(series, errors="coerce")


def _resolve_section(config, metadata, section_name):
    section = config.get(section_name)
    if not section:
        return {}

    resolved = {}
    if isinstance(section, dict):
        for name, definition in section.items():
            if isinstance(definition, dict):
                resolved[name] = definition
            elif isinstance(definition, str):
                source = metadata.get(section_name, {})
                if definition in source:
                    resolved[name] = source[definition]
                elif name in source:
                    resolved[name] = source[name]
                else:
                    raise ValueError(
                        f"Metadata {section_name} '{definition}' not found for '{name}'"
                    )
            else:
                raise ValueError(f"Invalid metadata entry for {section_name}: {name}")
    else:
        if isinstance(section, str):
            section = [section]
        if not isinstance(section, list):
            raise ValueError(f"{section_name} metadata must be a list, string, or dict.")

        for name in section:
            source = metadata.get(section_name, {})
            if name in source:
                resolved[name] = source[name]
            else:
                raise ValueError(f"Metadata {section_name} '{name}' not found")

    return resolved


def _select_definition(source_name, definitions):
    if not definitions:
        return None
    if source_name and source_name in definitions:
        return definitions[source_name]
    if len(definitions) == 1:
        return next(iter(definitions.values()))
    return None


def _apply_column_mapping(df, mapping):
    if not mapping:
        return df

    columns = mapping.get("columns", {})
    rename_map = {}

    for raw_name, target_name in columns.items():
        raw_name_norm = str(raw_name).strip().lower()
        target_name_norm = str(target_name).strip().lower()

        if raw_name_norm in df.columns:
            rename_map[raw_name_norm] = target_name_norm
        else:
            df[target_name_norm] = pd.NA

    df = df.rename(columns=rename_map)

    for target_name, definition in mapping.get("derived_columns", {}).items():
        target = str(target_name).strip().lower()
        operation = definition.get("operation")

        if operation == "copy":
            source = str(definition["source"]).strip().lower()
            df[target] = df[source] if source in df.columns else pd.NA
        elif operation == "multiply":
            columns = [str(name).strip().lower() for name in definition.get("columns", [])]
            if len(columns) != 2:
                raise ValueError(f"Derived column '{target}' multiply requires two columns")
            left = pd.to_numeric(df.get(columns[0]), errors="coerce")
            right = pd.to_numeric(df.get(columns[1]), errors="coerce")
            df[target] = left * right
            if definition.get("absolute", False):
                df[target] = df[target].abs()
            if definition.get("null_if_zero", False):
                df[target] = df[target].mask(df[target].eq(0))
        elif operation == "divide":
            columns = [str(name).strip().lower() for name in definition.get("columns", [])]
            if len(columns) != 2:
                raise ValueError(f"Derived column '{target}' divide requires two columns")
            numerator = pd.to_numeric(
                df.get(columns[0], pd.Series(pd.NA, index=df.index)),
                errors="coerce",
            )
            denominator = pd.to_numeric(
                df.get(columns[1], pd.Series(pd.NA, index=df.index)),
                errors="coerce",
            ).mask(lambda values: values.eq(0))
            df[target] = numerator / denominator
            if definition.get("absolute", False):
                df[target] = df[target].abs()
            if definition.get("null_if_zero", False):
                df[target] = df[target].mask(df[target].eq(0))
        elif operation == "coalesce_nonzero":
            columns = [str(name).strip().lower() for name in definition.get("columns", [])]
            if not columns:
                raise ValueError(
                    f"Derived column '{target}' coalesce_nonzero requires columns"
                )
            output = pd.Series(pd.NA, index=df.index, dtype="Float64")
            for column in columns:
                candidate = pd.to_numeric(
                    df.get(column, pd.Series(pd.NA, index=df.index)),
                    errors="coerce",
                ).astype("Float64")
                output = output.fillna(candidate.mask(candidate.eq(0)))
            df[target] = output
        elif operation == "inventory_movement_type":
            origin_name = str(definition["origin_usage"]).strip().lower()
            destination_name = str(definition["destination_usage"]).strip().lower()
            origin = df.get(origin_name, pd.Series(pd.NA, index=df.index)).astype("string")
            destination = df.get(
                destination_name, pd.Series(pd.NA, index=df.index)
            ).astype("string")
            movement = pd.Series("OTRO", index=df.index, dtype="string")
            origin_internal = origin.eq("internal").fillna(False)
            destination_internal = destination.eq("internal").fillna(False)
            movement.loc[~origin_internal & destination_internal] = "ENTRADA"
            movement.loc[origin_internal & ~destination_internal] = "SALIDA"
            movement.loc[origin_internal & destination_internal] = "TRASLADO"
            df[target] = movement
        else:
            raise ValueError(
                f"Unsupported derived column operation for '{target}': {operation}"
            )

    return df


def _apply_schema(df, schema, rules):
    if schema is None and rules is None:
        return df

    schema_columns = (schema or {}).get("columns", {})
    for name, props in schema_columns.items():
        target_name = str(name).strip().lower()
        if target_name not in df.columns:
            df[target_name] = pd.NA

        default_value = props.get("default")
        if default_value is not None:
            df[target_name] = df[target_name].fillna(default_value)

    string_rules = (rules or {}).get("string_cleaning", {})
    if string_rules:
        for col in df.select_dtypes(include=["object", "string"]).columns:
            df[col] = _normalize_string_series(df[col], string_rules)

    if schema is not None:
        for name, props in schema_columns.items():
            target_name = str(name).strip().lower()
            if target_name not in df.columns:
                continue

            dtype = str(props.get("type", "")).upper()

            if "DATETIME" in dtype or "TIMESTAMP" in dtype:
                formats = props.get("format") or props.get("formats")
                if isinstance(formats, str):
                    formats = [formats]
                df[target_name] = _normalize_date_series(df[target_name], formats)
            elif "DATE" in dtype:
                formats = props.get("format") or props.get("formats")
                if isinstance(formats, str):
                    formats = [formats]
                parsed = _normalize_date_series(df[target_name], formats)
                date_values = parsed.dt.date
                df[target_name] = date_values.where(parsed.notna(), None)
            elif any(token in dtype for token in ["INT", "BIGINT", "SMALLINT", "TINYINT"]):
                df[target_name] = pd.to_numeric(df[target_name], errors="coerce").astype("Int64")
            elif any(token in dtype for token in ["DECIMAL", "NUMERIC", "FLOAT", "REAL", "MONEY"]):
                amount_rules = (rules or {}).get("amount_normalization", {})
                if amount_rules:
                    df[target_name] = _normalize_amount_series(df[target_name], amount_rules)
                else:
                    df[target_name] = pd.to_numeric(df[target_name], errors="coerce")
            elif any(token in dtype for token in ["CHAR", "TEXT", "NVARCHAR", "VARCHAR", "STRING"]):
                df[target_name] = df[target_name].astype("string")
                if props.get("clean", True):
                    df[target_name] = _normalize_string_series(df[target_name], string_rules or {"trim": True, "collapse_spaces": True})
            else:
                df[target_name] = df[target_name]

            if default_value is not None:
                df[target_name] = df[target_name].fillna(default_value)

    if rules is not None:
        amount_rules = rules.get("amount_normalization")
        if amount_rules and schema is None:
            for col in amount_rules.get("columns", []):
                if col in df.columns:
                    df[col] = _normalize_amount_series(df[col], amount_rules)

    return df


def _build_required_columns(config, rules):
    required = set(str(col).strip().lower() for col in config.get("required_columns", []))
    if rules is not None:
        for col in rules.get("required_columns", []):
            required.add(str(col).strip().lower())
    return required


def _validate_required_columns(df, required_columns):
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Falta columna obligatoria: {', '.join(sorted(missing))}")


def _transform_source(df, source_name, config, metadata):
    mapping_definitions = _resolve_section(config, metadata, "mappings")
    schema_definitions = _resolve_section(config, metadata, "schemas")
    rule_definitions = _resolve_section(config, metadata, "rules")

    mapping = _select_definition(source_name, mapping_definitions)
    schema = _select_definition(source_name, schema_definitions)
    rules = _select_definition(source_name, rule_definitions)

    df = _apply_column_mapping(df, mapping)
    df = _apply_schema(df, schema, rules)
    return df


def apply_transforms(df, config):
    df = normalize_columns(df)
    if "__source" not in df.columns:
        df["__source"] = "default"

    metadata = _load_metadata(config)
    output_frames = []

    for source_name, group in df.groupby("__source", dropna=False):
        source_name = source_name or "default"
        group = group.copy()
        group = _transform_source(group, source_name, config, metadata)
        output_frames.append(group)

    df = pd.concat(output_frames, ignore_index=True) if output_frames else df
    df = normalize_columns(df)

    rule_definitions = _resolve_section(config, metadata, "rules")
    all_rules = None
    if rule_definitions:
        all_rules = next(iter(rule_definitions.values())) if len(rule_definitions) == 1 else None

    required_columns = _build_required_columns(config, all_rules)
    _validate_required_columns(df, required_columns)

    keys = config.get("keys", {})
    for key_name, cols in keys.items():
        for c in cols:
            if c not in df.columns:
                raise ValueError(f"Columna base faltante para {key_name}: {c}")

        key_parts = (
            df[cols]
            .astype(str)
            .apply(lambda x: x.str.strip())
            .replace({"nan": "", "None": ""})
        )
        df[key_name] = key_parts.agg("_".join, axis=1)
        df[key_name] = df[key_name].str.replace(r"_+", "_", regex=True).str.strip("_")
        if df[key_name].eq("").any():
            raise ValueError(f"{key_name} inválido generado (vacío)")

    for key_name in keys.keys():
        df = df.dropna(subset=[key_name])
        df = df.drop_duplicates(subset=[key_name])

    return df
