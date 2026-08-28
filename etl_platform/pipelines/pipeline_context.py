from dataclasses import dataclass, field

import pandas as pd

from etl_platform.core.config import load_config
from etl_platform.core.db.connection import get_engine


@dataclass
class PipelineContext:
    config_path: str
    config: dict
    engine: object
    process_name: str
    mode: str
    run_id: int | None = None
    current_step: str = "initialization"
    extracted_frames: list[pd.DataFrame] = field(default_factory=list)
    transformed_df: pd.DataFrame | None = None
    files_loaded: set[str] = field(default_factory=set)
    watermark_updates: list[dict] = field(default_factory=list)

    @classmethod
    def from_config_path(cls, config_path):
        config = load_config(config_path)
        engine = get_engine(config)
        return cls(
            config_path=config_path,
            config=config,
            engine=engine,
            process_name=config["process_name"],
            mode=config.get("load_mode", "incremental"),
        )

    @property
    def records_processed(self):
        if self.transformed_df is None:
            return 0
        return len(self.transformed_df)

    @property
    def has_data(self):
        return bool(self.extracted_frames)
