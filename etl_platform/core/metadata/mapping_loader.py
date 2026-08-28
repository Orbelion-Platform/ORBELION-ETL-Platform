import os
import glob
import yaml


def load_mappings(metadata_root, client=None):
    """Load mapping YAMLs.

    Loads generic mapping files from metadata_root/mappings/*.yaml and
    merges client-specific files from metadata_root/mappings/{client}.
    Client-specific metadata overrides generic definitions.

    Returns a dict {mapping_name: mapping_dict}
    """
    mappings = {}
    generic_files = glob.glob(os.path.join(metadata_root, 'mappings', '*.y*ml'))

    for f in sorted(generic_files):
        name = os.path.splitext(os.path.basename(f))[0]
        with open(f, 'r', encoding='utf-8') as fh:
            mappings[name] = yaml.safe_load(fh) or {}

    if client:
        client_dir = os.path.join(metadata_root, 'mappings', client)
        if os.path.isdir(client_dir):
            for f in sorted(glob.glob(os.path.join(client_dir, '*.y*ml'))):
                name = os.path.splitext(os.path.basename(f))[0]
                with open(f, 'r', encoding='utf-8') as fh:
                    mappings[name] = yaml.safe_load(fh) or {}

    return mappings
