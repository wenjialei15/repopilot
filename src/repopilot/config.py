from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from repopilot.adapters.paths import MAX_FILE_BYTES
from repopilot.fileio import read_regular_file
from repopilot.rules import load_yaml


class ScanConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    rules: dict[str, Literal["enabled", "disabled"]] = Field(default_factory=dict)

    @property
    def disabled_rules(self) -> frozenset[str]:
        return frozenset(
            rule for rule, state in self.rules.items() if state == "disabled"
        )


def read_config(path: Path) -> ScanConfig:
    raw = read_regular_file(path, MAX_FILE_BYTES)
    try:
        return ScanConfig.model_validate(load_yaml(raw.decode("utf-8-sig")))
    except (ValueError, ValidationError, yaml.YAMLError, RecursionError, OverflowError):
        raise ValueError("Invalid configuration. Expected a rules mapping.") from None
