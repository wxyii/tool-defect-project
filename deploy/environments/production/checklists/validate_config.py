#!/usr/bin/env python3
"""校验 P7 生产决策关闭、现场配置和技术供应链清单。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from tools.p7.preflight import validate_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-all-decisions", action="store_true")
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--closure", type=Path)
    parser.add_argument("--site-config", type=Path)
    parser.add_argument("--technology-inventory", type=Path)
    args = parser.parse_args(argv)
    return validate_config(
        repo_root=REPO_ROOT,
        registry_path=args.registry,
        closure_path=args.closure,
        site_config_path=args.site_config,
        inventory_path=args.technology_inventory,
    ).emit()


if __name__ == "__main__":
    raise SystemExit(main())
