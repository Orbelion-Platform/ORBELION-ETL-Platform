# Testing

The test suite is intentionally limited to components shipped in the public mirror.

Coverage includes:

- CSV, Excel, REST, SQL, and Odoo extraction behavior;
- REST retry, pagination, rate limiting, and dynamic authentication;
- metadata transformation and validation;
- staging, dimensions, facts, and watermark behavior;
- Azure SQL authentication configuration;
- pipeline step ordering, failure audit, and secret redaction;
- public-content sanitization and the synthetic demo.

Run:

```bash
python -m pytest -q -p no:cacheprovider
```
