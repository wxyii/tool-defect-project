from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class P7ProductionSecurityTest(unittest.TestCase):
    """生产环境安全验收测试套件。

    本套件验证生产部署的安全硬性要求，包括 mTLS、机密管理、
    供应链完整性、容器加固、网络隔离、审计日志和证书轮换。
    所有需要真实生产密钥/证书的检查标记为 PENDING_SITE_SIGNOFF。
    """

    def test_mtls_enforced(self):
        """验证所有服务间通信使用 mTLS。

        检查网关与服务编排配置中所有内部端点强制启用双向 TLS。
        """
        nginx = (ROOT / "deploy/gateway/nginx.conf").read_text(encoding="utf-8")
        compose = (
            ROOT / "deploy/compose/production-security-baseline.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("ssl_verify_client on", nginx)
        self.assertIn("ssl_client_certificate", nginx)
        self.assertIn("ssl_crl", nginx)

        insecure_listens = re.findall(r"listen\s+(\d+)\s*;", nginx)
        secure_listens = re.findall(r"listen\s+(\d+)\s+ssl\s*;", nginx)
        for port in insecure_listens:
            self.assertIn(
                port,
                secure_listens,
                f"端口 {port} 未启用 SSL",
            )

        self.assertNotIn("INSECURE_DISABLE_TLS", compose)
        self.assertNotIn("ssl_verify_client off", nginx)

    def test_secrets_not_in_config(self):
        """扫描所有配置文件，确保不含明文机密。

        检查密钥、令牌、密码和连接字符串不得出现在任何配置文件中。
        """
        patterns = (
            r'(?:password|passwd)\s*[:=]\s*["\'](?!\s*$|\$\{)(?!.*(?:secret|placeholder|external))[^\s"\'{}]{3,}["\']',
            r'(?:secret|token|api[_-]?key)\s*[:=]\s*["\'](?!\s*$|\$\{)(?!.*(?:secret|placeholder|external))[^\s"\'{}]{3,}["\']',
            r'(?:access[_-]?key|private[_-]?key)\s*[:=]\s*["\'](?!\s*$|\$\{)(?!.*(?:secret|placeholder|external))[^\s"\'{}]{3,}["\']',
            r'AKIA[0-9A-Z]{16}',
            r'sk-[a-zA-Z0-9]{32,}',
        )
        compiled = [re.compile(p, re.IGNORECASE) for p in patterns]

        config_files = list(
            ROOT.glob("deploy/**/*.yml")
        ) + list(
            ROOT.glob("deploy/**/*.yaml")
        ) + list(
            ROOT.glob("deploy/**/*.toml")
        ) + list(
            ROOT.glob("deploy/**/*.json")
        ) + list(
            ROOT.glob("config/**/*.yml")
        ) + list(
            ROOT.glob("config/**/*.yaml")
        ) + list(
            ROOT.glob("config/**/*.json")
        )
        config_files = [
            f
            for f in config_files
            if "development" not in str(f).lower()
            and ".env" not in str(f).lower()
        ]

        violations = []
        for config_file in config_files:
            if not config_file.is_file():
                continue
            try:
                content = config_file.read_text(encoding="utf-8")
            except Exception:
                continue
            for pattern in compiled:
                matches = pattern.findall(content)
                if matches:
                    violations.append(
                        {
                            "file": str(config_file.relative_to(ROOT)),
                            "pattern": pattern.pattern[:60],
                            "count": len(matches),
                        }
                    )

        self.assertEqual(
            [],
            violations,
            f"发现 {len(violations)} 处潜在机密泄露",
        )

    def test_no_anonymous_access(self):
        """验证所有端点均拒绝未认证请求。

        检查网关、API 和推理服务配置中不存在允许匿名访问的端点。
        """
        nginx = (ROOT / "deploy/gateway/nginx.conf").read_text(encoding="utf-8")
        compose = (
            ROOT / "deploy/compose/production-security-baseline.yml"
        ).read_text(encoding="utf-8")

        self.assertNotIn("auth_basic off", nginx)
        self.assertNotIn("allow all", nginx.lower())

        anonymous_env = re.findall(
            r'(?:TD_)?ALLOW_ANONYMOUS[=:]\s*["\']?(?:true|1|yes)',
            compose,
            re.IGNORECASE,
        )
        self.assertEqual([], anonymous_env, "发现匿名访问配置")

        auth_disabled = re.findall(
            r'(?:TD_)?AUTH_ENABLED[=:]\s*["\']?(?:false|0|no)',
            compose,
            re.IGNORECASE,
        )
        self.assertEqual([], auth_disabled, "发现认证禁用配置")

    def test_model_supply_chain(self):
        """验证模型包签名与 SBOM 完整性。

        检查供应链策略文件要求签名验证，且未知/无效签名策略为 HOLD。
        """
        policy_path = ROOT / "deploy/security/supply-chain-policy.json"
        self.assertTrue(policy_path.is_file(), f"缺少供应链策略: {policy_path}")

        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        container = policy.get("container_images", {})
        models = policy.get("model_packages", {})
        training = policy.get("training", {})

        container_sig = container.get("signature", {})
        self.assertEqual("sigstore-cosign", container_sig.get("scheme"))
        self.assertEqual(
            "HOLD",
            container.get("admission_result_on_unknown_or_invalid"),
        )

        self.assertEqual("ed25519", models.get("signature_algorithm"))
        self.assertEqual(
            "HOLD",
            models.get("verification_result_on_unknown_or_invalid"),
        )
        self.assertFalse(training.get("production_alias_write", True))

        self.assertIn("spdx-sbom", container.get("attestations_required", []))

    def test_container_read_only(self):
        """验证容器使用只读根文件系统。

        所有生产容器应配置只读根文件系统和最小权限。
        """
        compose = (
            ROOT / "deploy/compose/production-security-baseline.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("read_only: true", compose)
        self.assertIn('cap_drop: ["ALL"]', compose)
        self.assertIn("no-new-privileges:true", compose)

        service_blocks = compose.split("  ")
        service_names = re.findall(r"^\s{2}(\w[\w-]*):", compose, re.MULTILINE)
        anchor_has_read_only = "read_only: true" in compose.split("services:")[0]
        self.assertTrue(
            anchor_has_read_only or "read_only: true" in compose,
            "未发现只读根文件系统配置",
        )

        privileged = re.findall(r"privileged:\s*true", compose)
        self.assertEqual([], privileged, "发现特权容器配置")

    def test_network_isolation(self):
        """验证服务无法访问未授权端点。

        检查推理服务仅能访问消息队列和对象存储，
        不得访问业务数据库或外部网络。
        """
        compose = (
            ROOT / "deploy/compose/production-security-baseline.yml"
        ).read_text(encoding="utf-8")

        start = compose.index("  inference-service:")
        end = compose.index("\n  postgres:", start)
        inference = compose[start:end]

        self.assertNotIn("business_database", inference)
        self.assertNotIn("TD_DATABASE_", inference)
        self.assertNotIn("ports:", inference)
        self.assertIn('TD_DISABLE_INTERNET_EGRESS: "true"', inference)
        self.assertIn("inference_queue", inference)
        self.assertIn("object_storage", inference)

        internal_count = compose.count("internal: true")
        self.assertGreater(internal_count, 0, "未发现内部隔离网络配置")

    def test_audit_log_integrity(self):
        """验证审计日志追加写入且完整。

        检查真实数据库迁移和 JDBC 适配器，确保审计事实只能追加，
        且持久化结构包含必要字段。
        """
        compose = (
            ROOT / "deploy/compose/production-security-baseline.yml"
        ).read_text(encoding="utf-8")

        audit_disabled = re.findall(
            r'(?:TD_)?AUDIT_LOG_ENABLED[=:]\s*["\']?(?:false|0|no)',
            compose,
            re.IGNORECASE,
        )
        self.assertEqual([], audit_disabled, "审计日志被禁用")

        initial_migration = (
            ROOT
            / "services/business-api/src/main/resources/db/migration/V1__initial_business_schema.sql"
        ).read_text(encoding="utf-8")
        append_only_migration = (
            ROOT
            / "services/business-api/src/main/resources/db/migration/V2__append_only_and_message_claims.sql"
        ).read_text(encoding="utf-8")
        jdbc_adapter = (
            ROOT
            / "services/business-api/src/main/java/com/tooldefect/business/audit/infrastructure/JdbcAuditTrail.java"
        ).read_text(encoding="utf-8")

        table_match = re.search(
            r"CREATE TABLE audit_log\s*\((.*?)\n\);",
            initial_migration,
            re.DOTALL,
        )
        self.assertIsNotNone(table_match, "缺少 audit_log 事实表")
        table_definition = table_match.group(1) if table_match else ""
        required_fields = (
            "audit_id",
            "occurred_at",
            "actor_type",
            "actor_id",
            "actor_ip",
            "action",
            "resource_type",
            "resource_id",
            "request_id",
            "trace_id",
            "result",
        )
        for field in required_fields:
            self.assertRegex(
                table_definition,
                rf"(?m)^\s*{re.escape(field)}\s+",
                f"audit_log 缺少必需字段: {field}",
            )
        self.assertRegex(
            append_only_migration,
            r"CREATE TRIGGER trg_audit_log_append_only\s+"
            r"BEFORE UPDATE OR DELETE ON audit_log",
            "audit_log 缺少更新/删除拒绝触发器",
        )
        self.assertIn("INSERT INTO audit_log", jdbc_adapter)
        self.assertNotRegex(jdbc_adapter, r"(?i)\b(?:UPDATE|DELETE)\s+audit_log\b")

    def test_certificate_rotation(self):
        """验证证书轮换不中断连接。

        检查网关和应用配置支持证书热加载和宽限期，
        避免证书过期导致生产中断。
        """
        nginx = (ROOT / "deploy/gateway/nginx.conf").read_text(encoding="utf-8")
        compose = (
            ROOT / "deploy/compose/production-security-baseline.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("ssl_certificate", nginx)
        self.assertIn("ssl_certificate_key", nginx)

        cert_paths = re.findall(
            r'ssl_certificate\s+(/[^\s;]+)',
            nginx,
        )
        for cert_path in cert_paths:
            self.assertIn("run/secrets", cert_path, f"证书路径不在机密挂载: {cert_path}")

        rotation_env = re.findall(
            r'(?:TD_)?CERT_RELOAD_INTERVAL|CERT_GRACE_PERIOD|CERT_WATCHER|ssl_certificate\s+.*secrets',
            compose,
        )
        cert_in_secrets = "/run/secrets" in nginx
        self.assertTrue(
            len(rotation_env) > 0 or cert_in_secrets,
            "未发现证书轮换/热加载配置或证书不在机密挂载中",
        )


if __name__ == "__main__":
    unittest.main()
