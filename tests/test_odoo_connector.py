import logging
import xmlrpc.client

import pytest

from etl_platform.core.extract.connectors import odoo_connector


class FakeCommon:
    def authenticate(self, db, username, api_key, context):
        return 99


class FakeModels:
    def __init__(self):
        self.calls = []

    def execute_kw(self, db, uid, api_key, model, method, args, kwargs):
        self.calls.append({
            'db': db,
            'uid': uid,
            'model': model,
            'method': method,
            'args': args,
            'kwargs': kwargs,
        })
        return [
            {
                'id': 1,
                'name': 'Order 1',
                'partner_id': [7, 'Customer A'],
                'write_date': '2026-07-01 10:00:00',
            }
        ]


class FlakyModels(FakeModels):
    def __init__(self, secret_marker):
        super().__init__()
        self.secret_marker = secret_marker
        self.failures = 1

    def execute_kw(self, *args, **kwargs):
        if self.failures:
            self.failures -= 1
            raise xmlrpc.client.ProtocolError(
                f"https://{self.secret_marker}.example.com/xmlrpc/2/object",
                502,
                f"temporary {self.secret_marker}",
                {},
            )
        return super().execute_kw(*args, **kwargs)


class AnalyticalModels:
    def __init__(self):
        self.calls = []

    def execute_kw(self, db, uid, api_key, model, method, args, kwargs):
        self.calls.append({"model": model, "method": method, "args": args, "kwargs": kwargs})
        if method == "fields_get":
            return {"id": {"type": "integer"}, "order_id": {"type": "many2one"}}
        if model == "sale.order.line" and method == "search_read":
            return [{"id": 10, "order_id": [4, "SO004"]}]
        if model == "sale.order" and method == "read":
            return [{
                "id": 4,
                "name": "SO004",
                "partner_id": [8, "Customer B"],
                "team_id": [3, "E-commerce"],
            }]
        raise AssertionError((model, method))


class PaginatedModels:
    def __init__(self):
        self.calls = []
        self.records = [{"id": value} for value in range(1, 6)]

    def execute_kw(self, db, uid, api_key, model, method, args, kwargs):
        assert method == "search_read"
        self.calls.append(kwargs.copy())
        offset = kwargs["offset"]
        return self.records[offset:offset + kwargs["limit"]]


class CandidateModels:
    def __init__(self):
        self.calls = []

    def execute_kw(self, db, uid, api_key, model, method, args, kwargs):
        self.calls.append({"model": model, "method": method, "kwargs": kwargs})
        if model == "stock.valuation.layer" and method == "fields_get":
            raise xmlrpc.client.Fault(2, "model unavailable")
        if model == "stock.move" and method == "fields_get":
            return {
                "id": {"type": "integer"},
                "product_id": {"type": "many2one"},
                "quantity": {"type": "float"},
            }
        if model == "stock.move" and method == "search_read":
            return [{"id": 3, "product_id": [8, "Product"], "quantity": 2.0}]
        raise AssertionError((model, method))


class AggregateLookupModels:
    def __init__(self):
        self.calls = []

    def execute_kw(self, db, uid, api_key, model, method, args, kwargs):
        self.calls.append({"model": model, "method": method, "args": args, "kwargs": kwargs})
        if model == "stock.move" and method == "search_read":
            return [
                {"id": 1, "product_id": [8, "Product"], "quantity": 2.0},
                {"id": 2, "product_id": [8, "Product"], "quantity": -1.0},
            ]
        if model == "stock.quant" and method == "search_read":
            return [
                {"id": 10, "product_id": [8, "Product"], "quantity": 2.0, "value": 20.0},
                {"id": 11, "product_id": [8, "Product"], "quantity": 3.0, "value": 45.0},
            ]
        raise AssertionError((model, method))


def test_odoo_connector_returns_flattened_dataframe(monkeypatch):
    fake_models = FakeModels()
    monkeypatch.setattr(odoo_connector, '_odoo_clients', lambda url: (FakeCommon(), fake_models))
    monkeypatch.setenv('ODOO_URL', 'https://odoo.example.com')
    monkeypatch.setenv('ODOO_DB', 'db')
    monkeypatch.setenv('ODOO_USER', 'user')
    monkeypatch.setenv('ODOO_KEY', 'key')

    df = odoo_connector.extract_data({
        'type': 'odoo',
        'name': 'odoo_sale_order',
        'model': 'sale.order',
        'fields': ['id', 'name', 'partner_id', 'write_date'],
        'connection': {
            'url_env': 'ODOO_URL',
            'db_env': 'ODOO_DB',
            'username_env': 'ODOO_USER',
            'api_key_env': 'ODOO_KEY',
        },
    })

    assert df.loc[0, 'partner_id_id'] == 7
    assert df.loc[0, 'partner_id_name'] == 'Customer A'
    assert df.loc[0, '__source'] == 'odoo_sale_order'
    assert df.loc[0, '__odoo_model'] == 'sale.order'


def test_odoo_connector_adds_incremental_domain(monkeypatch):
    fake_models = FakeModels()
    monkeypatch.setattr(odoo_connector, '_odoo_clients', lambda url: (FakeCommon(), fake_models))
    monkeypatch.setenv('ODOO_URL', 'https://odoo.example.com')
    monkeypatch.setenv('ODOO_DB', 'db')
    monkeypatch.setenv('ODOO_USER', 'user')
    monkeypatch.setenv('ODOO_KEY', 'key')

    odoo_connector.extract_data({
        'type': 'odoo',
        'model': 'stock.quant',
        'fields': ['id', 'write_date'],
        'incremental_field': 'write_date',
        'connection': {
            'url_env': 'ODOO_URL',
            'db_env': 'ODOO_DB',
            'username_env': 'ODOO_USER',
            'api_key_env': 'ODOO_KEY',
        },
    }, watermark='2026-07-01 00:00:00')

    assert ['write_date', '>', '2026-07-01 00:00:00'] in fake_models.calls[0]['args'][0]


def test_odoo_connector_requires_missing_secret_env(monkeypatch):
    monkeypatch.delenv('MISSING_ODOO_URL', raising=False)

    with pytest.raises(odoo_connector.OdooConnectorError, match='Missing required Odoo environment variable'):
        odoo_connector.extract_data({
            'type': 'odoo',
            'model': 'res.partner',
            'connection': {'url_env': 'MISSING_ODOO_URL'},
        })


def test_odoo_connector_retries_protocol_errors_without_logging_values(monkeypatch, caplog):
    secret_marker = "must-not-appear"
    fake_models = FlakyModels(secret_marker)
    monkeypatch.setattr(odoo_connector, '_odoo_clients', lambda url: (FakeCommon(), fake_models))
    monkeypatch.setattr(odoo_connector.time, "sleep", lambda seconds: None)
    monkeypatch.setenv('ODOO_URL', 'https://odoo.example.com')
    monkeypatch.setenv('ODOO_DB', 'db')
    monkeypatch.setenv('ODOO_USER', 'user')
    monkeypatch.setenv('ODOO_KEY', 'key')

    with caplog.at_level(logging.WARNING, logger=odoo_connector.__name__):
        df = odoo_connector.extract_data({
            'type': 'odoo',
            'model': 'sale.order',
            'fields': ['id', 'name'],
            'connection': {
                'url_env': 'ODOO_URL',
                'db_env': 'ODOO_DB',
                'username_env': 'ODOO_USER',
                'api_key_env': 'ODOO_KEY',
            },
        })

    assert df.loc[0, 'name'] == 'Order 1'
    assert "operation=search_read" in caplog.text
    assert "error=ProtocolError" in caplog.text
    assert "retry=true" in caplog.text
    assert secret_marker not in caplog.text


def test_odoo_connector_filters_optional_fields_and_enriches_lookups(monkeypatch):
    fake_models = AnalyticalModels()
    monkeypatch.setattr(odoo_connector, '_odoo_clients', lambda url: (FakeCommon(), fake_models))
    monkeypatch.setenv('ODOO_URL', 'https://odoo.example.com')
    monkeypatch.setenv('ODOO_DB', 'db')
    monkeypatch.setenv('ODOO_USER', 'user')
    monkeypatch.setenv('ODOO_KEY', 'key')

    df = odoo_connector.extract_data({
        'type': 'odoo',
        'model': 'sale.order.line',
        'fields': ['id', 'order_id'],
        'optional_fields': ['purchase_price'],
        'lookups': [{
            'local_field': 'order_id_id',
            'model': 'sale.order',
            'fields': ['name', 'partner_id', 'team_id'],
            'prefix': 'order_',
        }],
        'connection': {
            'url_env': 'ODOO_URL', 'db_env': 'ODOO_DB',
            'username_env': 'ODOO_USER', 'api_key_env': 'ODOO_KEY',
        },
    })

    search_call = next(call for call in fake_models.calls if call['method'] == 'search_read')
    assert search_call['kwargs']['fields'] == ['id', 'order_id']
    assert df.loc[0, 'order_partner_id_id'] == 8
    assert df.loc[0, 'order_team_id_name'] == 'E-commerce'


def test_odoo_connector_paginates_until_the_last_partial_page(monkeypatch):
    fake_models = PaginatedModels()
    monkeypatch.setattr(odoo_connector, '_odoo_clients', lambda url: (FakeCommon(), fake_models))
    monkeypatch.setenv('ODOO_URL', 'https://odoo.example.com')
    monkeypatch.setenv('ODOO_DB', 'db')
    monkeypatch.setenv('ODOO_USER', 'user')
    monkeypatch.setenv('ODOO_KEY', 'key')

    df = odoo_connector.extract_data({
        'type': 'odoo', 'model': 'stock.valuation.layer', 'fields': ['id'],
        'page_size': 2,
        'connection': {
            'url_env': 'ODOO_URL', 'db_env': 'ODOO_DB',
            'username_env': 'ODOO_USER', 'api_key_env': 'ODOO_KEY',
        },
    })

    assert df['id'].tolist() == [1, 2, 3, 4, 5]
    assert [call['offset'] for call in fake_models.calls] == [0, 2, 4]


def test_odoo_connector_selects_first_compatible_model_candidate(monkeypatch):
    fake_models = CandidateModels()
    monkeypatch.setattr(odoo_connector, '_odoo_clients', lambda url: (FakeCommon(), fake_models))
    monkeypatch.setenv('ODOO_URL', 'https://odoo.example.com')
    monkeypatch.setenv('ODOO_DB', 'db')
    monkeypatch.setenv('ODOO_USER', 'user')
    monkeypatch.setenv('ODOO_KEY', 'key')

    df = odoo_connector.extract_data({
        'type': 'odoo',
        'name': 'odoo_inventory',
        'model_candidates': [
            {
                'name': 'odoo_stock_valuation_layer',
                'model': 'stock.valuation.layer',
                'fields': ['id'],
            },
            {
                'name': 'odoo_stock_move',
                'model': 'stock.move',
                'fields': ['id', 'product_id', 'quantity'],
            },
        ],
        'connection': {
            'url_env': 'ODOO_URL', 'db_env': 'ODOO_DB',
            'username_env': 'ODOO_USER', 'api_key_env': 'ODOO_KEY',
        },
    })

    assert df.loc[0, '__source'] == 'odoo_stock_move'
    assert df.loc[0, '__odoo_model'] == 'stock.move'
    assert [
        (call['model'], call['method']) for call in fake_models.calls[:3]
    ] == [
        ('stock.valuation.layer', 'fields_get'),
        ('stock.move', 'fields_get'),
        ('stock.move', 'search_read'),
    ]


def test_odoo_connector_rejects_candidates_missing_required_fields(monkeypatch):
    fake_models = CandidateModels()
    monkeypatch.setattr(odoo_connector, '_odoo_clients', lambda url: (FakeCommon(), fake_models))
    monkeypatch.setenv('ODOO_URL', 'https://odoo.example.com')
    monkeypatch.setenv('ODOO_DB', 'db')
    monkeypatch.setenv('ODOO_USER', 'user')
    monkeypatch.setenv('ODOO_KEY', 'key')

    with pytest.raises(odoo_connector.OdooConnectorError, match='No compatible Odoo model'):
        odoo_connector.extract_data({
            'type': 'odoo',
            'model_candidates': [{
                'model': 'stock.move',
                'fields': ['id', 'missing_field'],
            }],
            'connection': {
                'url_env': 'ODOO_URL', 'db_env': 'ODOO_DB',
                'username_env': 'ODOO_USER', 'api_key_env': 'ODOO_KEY',
            },
        })


def test_odoo_connector_enriches_rows_with_related_model_aggregates(monkeypatch):
    fake_models = AggregateLookupModels()
    monkeypatch.setattr(odoo_connector, '_odoo_clients', lambda url: (FakeCommon(), fake_models))
    monkeypatch.setenv('ODOO_URL', 'https://odoo.example.com')
    monkeypatch.setenv('ODOO_DB', 'db')
    monkeypatch.setenv('ODOO_USER', 'user')
    monkeypatch.setenv('ODOO_KEY', 'key')

    df = odoo_connector.extract_data({
        'type': 'odoo',
        'model': 'stock.move',
        'fields': ['id', 'product_id', 'quantity'],
        'aggregate_lookups': [{
            'local_field': 'product_id_id',
            'model': 'stock.quant',
            'remote_field': 'product_id',
            'fields': ['product_id', 'quantity', 'value'],
            'prefix': 'quant_',
            'aggregations': {
                'quantity': {'field': 'quantity', 'operation': 'sum'},
                'value': {'field': 'value', 'operation': 'sum'},
            },
        }],
        'connection': {
            'url_env': 'ODOO_URL', 'db_env': 'ODOO_DB',
            'username_env': 'ODOO_USER', 'api_key_env': 'ODOO_KEY',
        },
    })

    assert df['quant_quantity'].tolist() == [5.0, 5.0]
    assert df['quant_value'].tolist() == [65.0, 65.0]
    quant_call = next(
        call for call in fake_models.calls
        if call['model'] == 'stock.quant' and call['method'] == 'search_read'
    )
    assert ['product_id', 'in', [8]] in quant_call['args'][0]
