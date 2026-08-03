#!/usr/bin/env python3
"""无需 Maven 或容器的后端结构、迁移和领域验证。"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile


SERVICE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVICE_ROOT.parents[1]
JAVA_ROOT = SERVICE_ROOT / "src/main/java"
TEST_HARNESS = (
    SERVICE_ROOT
    / "src/test/java/com/tooldefect/business/OfflineDomainTest.java"
)
MIGRATION_ROOT = SERVICE_ROOT / "src/main/resources/db/migration"

REQUIRED_MODULES = {
    "capture",
    "detection",
    "review",
    "storage",
    "dataset",
    "model",
    "device",
    "identity",
    "audit",
    "shared",
    "sample",
}

def verify_architecture() -> list[str]:
    errors: list[str] = []
    base = JAVA_ROOT / "com/tooldefect/business"
    modules = {path.name for path in base.iterdir() if path.is_dir()}
    missing = REQUIRED_MODULES - modules
    if missing:
        errors.append(f"缺少后端模块：{sorted(missing)}")
    for module in sorted(REQUIRED_MODULES - {"shared"}):
        module_root = base / module
        missing_layers = {
            layer
            for layer in ("api", "application", "domain", "infrastructure")
            if not (module_root / layer).is_dir()
        }
        if missing_layers:
            errors.append(
                f"模块 {module} 缺少分层：{sorted(missing_layers)}"
            )

    import_pattern = re.compile(r"^import\s+([^;]+);", re.MULTILINE)
    for source in sorted(JAVA_ROOT.rglob("*.java")):
        text = source.read_text(encoding="utf-8")
        imports = import_pattern.findall(text)
        relative = source.relative_to(JAVA_ROOT).as_posix()
        if "/domain/" in f"/{relative}":
            for imported in imports:
                if (
                    imported.startswith("org.springframework")
                    or imported.startswith("jakarta.persistence")
                    or ".infrastructure." in imported
                    or "rabbit" in imported.lower()
                ):
                    errors.append(f"领域层非法依赖：{relative} -> {imported}")
        parts = relative.split("/")
        try:
            root_index = parts.index("business")
            own_module = parts[root_index + 1]
        except (ValueError, IndexError):
            continue
        for imported in imports:
            match = re.search(
                r"com\.tooldefect\.business\.([a-z_]+)\.infrastructure",
                imported,
            )
            if match and match.group(1) != own_module:
                errors.append(f"模块越界访问基础设施：{relative} -> {imported}")
    return errors


def verify_migrations() -> list[str]:
    errors: list[str] = []
    migrations = sorted(MIGRATION_ROOT.glob("V*__*.sql"))
    versions = [int(path.name.split("__", 1)[0][1:]) for path in migrations]
    if versions != list(range(1, len(versions) + 1)):
        errors.append(f"迁移版本不连续：{versions}")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in migrations)
    required_tables = {
        "production_line",
        "station",
        "device",
        "capture_event",
        "image_object",
        "detection_task",
        "detection_attempt",
        "detection_result",
        "disposition_record",
        "review_task",
        "review_record",
        "dataset_version",
        "training_run",
        "model_version",
        "model_deployment",
        "sys_user",
        "audit_log",
        "outbox_event",
        "inbox_message",
        "reliability_issue",
        "maintenance_action",
        "recovery_point",
        "recovery_drill",
    }
    created = set(re.findall(r"CREATE TABLE\s+([a-z_]+)", combined, re.I))
    if required_tables - created:
        errors.append(f"迁移缺表：{sorted(required_tables - created)}")
    required_fragments = (
        "ck_capture_finalized_disposition",
        "UNIQUE (detection_task_id",
        "confidence BETWEEN 0 AND 1",
        "result_sha256",
        "td_reject_fact_mutation",
        "payload ? 'base64'",
        "trg_image_object_state_guard",
        "uq_inbox_consumer_detection_task",
        "record_version must advance exactly once",
    )
    for fragment in required_fragments:
        if fragment.lower() not in combined.lower():
            errors.append(f"迁移缺少约束语义：{fragment}")
    forbidden = re.compile(r"\b(bytea|largeobject|lo_import)\b", re.I)
    if forbidden.search(combined):
        errors.append("数据库迁移不得保存图片、模型或大数组二进制")
    outbox_repository = (
        JAVA_ROOT
        / "com/tooldefect/business/shared/infrastructure/JdbcOutboxRepository.java"
    ).read_text(encoding="utf-8")
    if "FOR UPDATE SKIP LOCKED" not in outbox_repository:
        errors.append("JDBC 发件箱缺少可执行的 SKIP LOCKED 原子领取")
    return errors


def compile_and_run() -> tuple[int, str]:
    sources = sorted(JAVA_ROOT.glob("com/tooldefect/business/*/domain/*.java"))
    sources.extend(
        sorted(
            (
                JAVA_ROOT
                / "com/tooldefect/business/shared/messaging"
            ).glob("*.java")
        )
    )
    sources.extend(
        [
            JAVA_ROOT
            / "com/tooldefect/business/storage/application/ObjectKeyPolicy.java",
            JAVA_ROOT
            / "com/tooldefect/business/shared/application/MessagePublisher.java",
            JAVA_ROOT
            / "com/tooldefect/business/shared/application/NonRetryableMessageException.java",
            JAVA_ROOT
            / "com/tooldefect/business/shared/application/OutboxRepository.java",
            JAVA_ROOT
            / "com/tooldefect/business/shared/application/ReliableMessagingService.java",
        ]
    )
    sources.append(TEST_HARNESS)
    with tempfile.TemporaryDirectory(prefix="td-business-javac-") as temporary:
        output = Path(temporary) / "classes"
        output.mkdir()
        compile_result = subprocess.run(
            ["javac", "-encoding", "UTF-8", "-d", str(output)]
            + [str(path) for path in sources],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if compile_result.returncode:
            return compile_result.returncode, compile_result.stdout + compile_result.stderr
        run_result = subprocess.run(
            [
                "java",
                "-ea",
                "-cp",
                str(output),
                "com.tooldefect.business.OfflineDomainTest",
            ],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        return run_result.returncode, run_result.stdout + run_result.stderr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-java",
        action="store_true",
        help="只执行结构与迁移检查",
    )
    args = parser.parse_args()

    errors = verify_architecture() + verify_migrations()
    if errors:
        for error in errors:
            print(f"错误：{error}", file=sys.stderr)
        return 1
    if not args.skip_java:
        code, output = compile_and_run()
        print(output, end="")
        if code:
            return code
    print("business-api 结构、迁移静态语义与纯领域检查：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
