#!/usr/bin/env python3
"""复用 P6 供应链门禁重新验签生产模型包。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from tools.p7.preflight import validate_model_package


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path)
    parser.add_argument("--trusted-keys", type=Path)
    args = parser.parse_args(argv)
    return validate_model_package(
        repo_root=REPO_ROOT,
        package_dir=args.package_dir,
        trusted_keys_path=args.trusted_keys,
    ).emit()


if __name__ == "__main__":
    raise SystemExit(main())
