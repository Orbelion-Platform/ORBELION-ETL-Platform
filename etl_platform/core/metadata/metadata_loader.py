import os
from .mapping_loader import load_mappings
from .schema_loader import load_schemas
import glob
import yaml


def _resolve_rules_dir(metadata_root):
    for candidate in ('rules', 'Rules'):
        candidate_dir = os.path.join(metadata_root, candidate)
        if os.path.isdir(candidate_dir):
            return candidate_dir
    return os.path.join(metadata_root, 'rules')


def load_rules(metadata_root, client=None):
    rules = {}
    rules_root = _resolve_rules_dir(metadata_root)

    generic_files = glob.glob(os.path.join(rules_root, '*.y*ml'))
    for f in sorted(generic_files):
        name = os.path.splitext(os.path.basename(f))[0]
        with open(f, 'r', encoding='utf-8') as fh:
            rules[name] = yaml.safe_load(fh) or {}

    if client:
        client_dir = os.path.join(rules_root, client)
        if os.path.isdir(client_dir):
            for f in sorted(glob.glob(os.path.join(client_dir, '*.y*ml'))):
                name = os.path.splitext(os.path.basename(f))[0]
                with open(f, 'r', encoding='utf-8') as fh:
                    rules[name] = yaml.safe_load(fh) or {}

    return rules


def load_all(metadata_root, client=None):
    return {
        'mappings': load_mappings(metadata_root, client),
        'schemas': load_schemas(metadata_root, client),
        'rules': load_rules(metadata_root, client),
    }
