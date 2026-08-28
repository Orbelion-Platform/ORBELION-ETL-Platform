# Azure deployment example

This document describes configuration boundaries only. It does not create Azure resources.

## Required external configuration

- Microsoft Entra tenant and workload application IDs;
- GitHub Environment variables for Azure OIDC login;
- an Azure SQL server/database and database roles appropriate to the job;
- an Azure Key Vault name and Managed Identity access;
- four Odoo secrets named from the technical client ID;

## Secret naming example

For `example_client`, underscores are converted to Key Vault-safe hyphens:

```text
example-client-odoo-url
example-client-odoo-database
example-client-odoo-username
example-client-odoo-api-key
```

Use repository/environment variables for resource identifiers. Do not commit actual values to YAML, workflow files, or documentation.

## Execution

The public Azure workflow is manual-only. It validates placeholder configuration, signs in with Azure OIDC, and verifies that the configured Key Vault resource is reachable without reading secret values or running an ETL deployment.
