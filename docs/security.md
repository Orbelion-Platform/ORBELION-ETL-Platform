# Security model

## Secrets

The repository contains no runtime secrets. The Azure example receives its Key Vault name and identity IDs through GitHub Environment variables. Its manual verification step checks only that the configured vault is reachable and does not read secret values.

## GitHub Actions

Workflow permissions default to empty. Test jobs receive `contents: read`; the ETL job additionally receives `id-token: write` for Azure OIDC. Cloud identifiers remain repository/environment variables.

## Publication control

Run the test suite before every public commit:

```bash
python -m pytest -q
```

Use a standard secret scanner such as gitleaks when it is available in the development or CI environment.
