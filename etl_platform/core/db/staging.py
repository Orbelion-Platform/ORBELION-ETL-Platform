from datetime import datetime

from sqlalchemy import text


class StagingContractError(ValueError):
    """Safe diagnostic raised before staging data is modified."""


def get_table_columns(engine, schema, table):
    sql = text("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = :schema
          AND TABLE_NAME = :table
        ORDER BY ORDINAL_POSITION
    """)

    with engine.begin() as conn:
        return [
            row[0]
            for row in conn.execute(sql, {"schema": schema, "table": table})
        ]


def get_table_contract(engine, schema, table):
    sql = text("""
        SELECT
            COLUMN_NAME,
            DATA_TYPE,
            CHARACTER_MAXIMUM_LENGTH,
            NUMERIC_PRECISION,
            NUMERIC_SCALE,
            IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = :schema
          AND TABLE_NAME = :table
        ORDER BY ORDINAL_POSITION
    """)

    with engine.begin() as conn:
        rows = conn.execute(sql, {"schema": schema, "table": table})
        return {
            row[0]: {
                "data_type": str(row[1]).lower(),
                "max_length": row[2],
                "precision": row[3],
                "scale": row[4],
                "nullable": str(row[5]).upper() == "YES",
            }
            for row in rows
        }


def validate_staging_values(df, contract, schema, table, load_columns):
    for column in load_columns:
        metadata = contract[column]
        series = df[column]

        if not metadata["nullable"]:
            null_count = int(series.isna().sum())
            if null_count:
                raise StagingContractError(
                    f"{schema}.{table}.{column} does not allow NULL; "
                    f"rows_with_null={null_count}"
                )

        max_length = metadata["max_length"]
        if (
            metadata["data_type"] in {"char", "nchar", "varchar", "nvarchar"}
            and max_length not in (None, -1)
        ):
            lengths = series.dropna().astype("string").str.len()
            observed = int(lengths.max()) if not lengths.empty else 0
            if observed > int(max_length):
                raise StagingContractError(
                    f"{schema}.{table}.{column} exceeds its configured length; "
                    f"maximum={max_length} observed={observed}"
                )

        if metadata["data_type"] == "date":
            rows_with_time = sum(
                isinstance(value, datetime)
                for value in series.dropna().tolist()
            )
            if rows_with_time:
                raise StagingContractError(
                    f"{schema}.{table}.{column} requires date-only values; "
                    f"rows_with_time={rows_with_time}"
                )

        if metadata["data_type"] in {"decimal", "numeric"}:
            precision = metadata["precision"]
            scale = metadata["scale"]
            if precision is None or scale is None:
                continue
            numeric = series.dropna()
            if numeric.empty:
                continue
            limit = 10 ** (int(precision) - int(scale))
            overflow = numeric.abs() >= limit
            if bool(overflow.any()):
                raise StagingContractError(
                    f"{schema}.{table}.{column} exceeds numeric precision; "
                    f"precision={precision} scale={scale}"
                )


def load_staging(engine, df, config):

    table = config["staging_table"]
    schema = config["schema"]
    table_columns = get_table_columns(engine, schema, table)
    load_columns = [col for col in table_columns if col in df.columns]

    if not load_columns:
        raise ValueError(f"No hay columnas compatibles para cargar {schema}.{table}")

    contract = get_table_contract(engine, schema, table)
    validate_staging_values(df, contract, schema, table, load_columns)

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {schema}.{table}"))
        df[load_columns].to_sql(
            name=table,
            con=conn,
            schema=schema,
            if_exists="append",
            index=False
        )
