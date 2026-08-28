def merge_dimension(
    engine,
    dim_table,
    stg_table,
    natural_key,
    columns,
    column_sources=None,
):

    column_sources = column_sources or {}

    update_cols = [c for c in columns if c != natural_key]

    update_clause = ", ".join([f"{c}=s.{c}" for c in update_cols])
    insert_cols = ", ".join(columns)
    insert_vals = ", ".join([f"s.{c}" for c in columns])
    natural_source = column_sources.get(natural_key, natural_key)
    source_cols = ", ".join(
        [f"{natural_source} AS {natural_key}"]
        + [f"MAX({column_sources.get(c, c)}) AS {c}" for c in update_cols]
    )
    group_cols = natural_source

    sql = f"""
    MERGE {dim_table} AS t
    USING (
        SELECT {source_cols}
        FROM {stg_table}
        WHERE {natural_source} IS NOT NULL
        GROUP BY {group_cols}
    ) AS s
    ON t.{natural_key} = s.{natural_key}
    WHEN MATCHED THEN UPDATE SET {update_clause}
    WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals});
    """

    with engine.begin() as conn:
        conn.exec_driver_sql(sql)


def load_dimensions(engine, config):

    dims = config.get("dimensions", [])

    for dim in dims:

        merge_dimension(
            engine,
            f"{config['schema']}.{dim['name']}",
            f"{config['schema']}.{config['staging_table']}",
            dim["natural_key"],
            list(dim["columns"].keys()),
            dim.get("column_sources"),
        )
