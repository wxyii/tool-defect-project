#!/usr/bin/env python3
"""校验生产环境文件的不可变镜像标识并拒绝明文机密。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from tools.p7.preflight import validate_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=REPO_ROOT / "deploy/environments/production/.env",
    )
    args = parser.parse_args(argv)
    return validate_env(repo_root=REPO_ROOT, env_path=args.env_file).emit()


if __name__ == "__main__":
    raise SystemExit(main())
