# Local synthetic demo

The demo proves the file connector and metadata transformation path without using a database or network service.

## Run

```bash
python -m pip install -r requirements.txt
python -m demo.run_demo
```

Expected console output:

```text
DEMO_OK rows=4 total=408.50 output=data/output/orders_transformed.csv
```

The input under `demo/data/` is synthetic. The output directory is ignored by Git and can be regenerated at any time.

## What it exercises

- CSV connector discovery and source metadata;
- YAML mapping, schema, and validation rule loading;
- amount/date coercion;
- derived `total` calculation;
- deterministic `order_line_key` generation;
- transformed CSV output.

