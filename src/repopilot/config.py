from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from repopilot.adapters.paths import MAX_FILE_BYTES
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
    if not path.is_file():
        raise ValueError("Expected a configuration file.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("Configuration file exceeds the size limit.")
    try:
        return ScanConfig.model_validate(load_yaml(raw.decode("utf-8-sig")))
    except (ValueError, ValidationError, yaml.YAMLError, RecursionError, OverflowError):
        raise ValueError("Invalid configuration. Expected a rules mapping.") from None
