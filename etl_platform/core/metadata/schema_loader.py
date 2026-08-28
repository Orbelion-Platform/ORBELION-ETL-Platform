import os
import glob
import yaml


def load_schemas(metadata_root, client=None):
    """Load schema definitions.

    Loads generic schema files from metadata_root/schemas/*.yaml and
    merges client-specific files from metadata_root/schemas/{client}.
    Client-specific metadata overrides generic definitions.
    Returns dict {schema_name: schema_dict}
    """
    schemas = {}
    generic_files = glob.glob(os.path.join(metadata_root, 'schemas', '*.y*ml'))

    for f in sorted(generic_files):
        name = os.path.splitext(os.path.basename(f))[0]
        with open(f, 'r', encoding='utf-8') as fh:
            schemas[name] = yaml.safe_load(fh) or {}

    if client:
        client_dir = os.path.join(metadata_root, 'schemas', client)
        if os.path.isdir(client_dir):
            for f in sorted(glob.glob(os.path.join(client_dir, '*.y*ml'))):
                name = os.path.splitext(os.path.basename(f))[0]
                with open(f, 'r', encoding='utf-8') as fh:
                    schemas[name] = yaml.safe_load(fh) or {}

    return schemas
