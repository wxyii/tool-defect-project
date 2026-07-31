#!/usr/bin/env python3
"""执行 unittest 目录，并拒绝跳过或预期失败造成的假绿。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def run_suite(start_directory: Path, verbosity: int = 1) -> int:
    if not start_directory.is_dir():
        print(f"严格测试失败：测试目录不存在：{start_directory}", file=sys.stderr)
        return 2

    suite = unittest.defaultTestLoader.discover(str(start_directory))
    test_count = suite.countTestCases()
    if test_count == 0:
        print(f"严格测试失败：没有发现测试：{start_directory}", file=sys.stderr)
        return 2

    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    incomplete = []
    incomplete.extend(
        f"跳过：{test.id()}：{reason}"
        for test, reason in result.skipped
    )
    incomplete.extend(
        f"预期失败：{test.id()}"
        for test, _traceback in result.expectedFailures
    )
    incomplete.extend(
        f"意外成功：{test.id()}"
        for test in result.unexpectedSuccesses
    )
    if incomplete:
        print(
            f"严格测试失败：{len(incomplete)} 项未形成普通通过结果。",
            file=sys.stderr,
        )
        for item in incomplete:
            print(f"- {item}", file=sys.stderr)
        return 2
    return 0 if result.wasSuccessful() else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="严格执行 unittest 测试目录")
    parser.add_argument("start_directory", type=Path)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    return run_suite(args.start_directory.resolve(), 2 if args.verbose else 1)


if __name__ == "__main__":
    raise SystemExit(main())
