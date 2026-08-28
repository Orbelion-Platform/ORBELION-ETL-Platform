from sqlalchemy import text


def load_facts(engine, config):

    schema = config["schema"]
    facts = config.get("facts", [])

    for fact in facts:

        fact_name = fact["name"]
        business_key = fact.get("business_key")  # CLAVE DINÁMICA
        columns = fact.get("columns", {})
        query = fact["query"]

        if not business_key:
            raise ValueError(f"Fact {fact_name} requiere 'business_key'")

        cols = list(columns.keys())

        # =========================
        # BUILD UPDATE
        # =========================
        update_clause = ", ".join([
            f"t.{col} = s.{col}" for col in cols if col != business_key
        ])

        # =========================
        # BUILD INSERT
        # =========================
        insert_cols = ", ".join(cols)
        insert_vals = ", ".join([f"s.{col}" for col in cols])

        merge_sql = f"""
        MERGE {schema}.{fact_name} AS t
        USING (
            {query}
        ) AS s
        ON t.{business_key} = s.{business_key}

        WHEN MATCHED THEN
            UPDATE SET {update_clause}

        WHEN NOT MATCHED THEN
            INSERT ({insert_cols})
            VALUES ({insert_vals});
        """

        with engine.begin() as conn:
            conn.execute(text(merge_sql))