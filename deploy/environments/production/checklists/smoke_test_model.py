#!/usr/bin/env python3
"""验证真实生产推理服务生成的结构化模型冒烟证据。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from tools.p7.preflight import validate_smoke_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args(argv)
    return validate_smoke_evidence(
        repo_root=REPO_ROOT,
        evidence_path=args.evidence,
    ).emit()


if __name__ == "__main__":
    raise SystemExit(main())
