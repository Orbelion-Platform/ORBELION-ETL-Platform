from __future__ import annotations

from pathlib import Path

import yaml

from etl_platform.core.extract.extract_dynamic import extract_data
from etl_platform.core.transform.transform_basic import apply_transforms


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def run_demo(output_path: Path | None = None):
    config_path = REPOSITORY_ROOT / "demo" / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["__config_path__"] = str(config_path)
    config["metadata_root"] = str(REPOSITORY_ROOT / "metadata")

    source = dict(config["sources"][0])
    source["path"] = str(REPOSITORY_ROOT / source["path"])

    extracted = extract_data(source)
    transformed = apply_transforms(extracted, config)

    destination = output_path or REPOSITORY_ROOT / "data" / "output" / "orders_transformed.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    transformed.to_csv(destination, index=False)
    return transformed, destination


def main():
    transformed, destination = run_demo()
    relative_output = destination.relative_to(REPOSITORY_ROOT).as_posix()
    print(
        f"DEMO_OK rows={len(transformed)} "
        f"total={transformed['total'].sum():.2f} output={relative_output}"
    )


if __name__ == "__main__":
    main()

