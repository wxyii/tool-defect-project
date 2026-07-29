"""Portable project configuration."""

from dataclasses import dataclass
import json
from pathlib import Path, PureWindowsPath
from typing import Any, Dict


@dataclass(frozen=True)
class ProjectConfig:
    project_root: Path
    values: Dict[str, Any]

    @property
    def image_size(self) -> int:
        return int(self.values["image_size"])

    def path(self, name: str) -> Path:
        relative = Path(self.values["paths"][name])
        return self.project_root / relative

    def get(self, name: str, default=None):
        return self.values.get(name, default)


def load_config(config_path):
    config_path = Path(config_path).absolute()
    with config_path.open(encoding="utf-8") as handle:
        values = json.load(handle)

    paths = values.get("paths", {})
    for name, value in paths.items():
        candidate = Path(value)
        windows_candidate = PureWindowsPath(str(value))
        if candidate.is_absolute() or windows_candidate.is_absolute():
            raise ValueError(f"configuration path '{name}' must be project-relative")

    project_root = (
        config_path.parent.parent
        if config_path.parent.name.lower() == "configs"
        else config_path.parent
    )
    return ProjectConfig(project_root=project_root, values=values)
