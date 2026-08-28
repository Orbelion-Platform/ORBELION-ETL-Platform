from .api_connector import extract_data as extract_api
from .csv_connector import extract_data as extract_csv
from .excel_connector import extract_data as extract_excel
from .sql_connector import extract_data as extract_sql
from .odoo_connector import extract_data as extract_odoo

CONNECTOR_REGISTRY = {
    "csv": extract_csv,
    "excel": extract_excel,
    "api": extract_api,
    "rest": extract_api,
    "database": extract_sql,
    "odoo": extract_odoo,
}


def get_connector(source_type):
    if source_type not in CONNECTOR_REGISTRY:
        raise ValueError(f"Connector no soportado: {source_type}")
    return CONNECTOR_REGISTRY[source_type]
