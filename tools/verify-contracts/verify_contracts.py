#!/usr/bin/env python3
"""离线验证 JSON Schema、OpenAPI、AsyncAPI、示例及状态机。"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from schema_engine import SchemaEngine, ValidationError

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
WRITE_METHODS = {"post", "put", "patch", "delete"}
FIVE_CASES = {"success", "duplicate", "conflict", "unauthorized", "validation_error"}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def mutate(document: Any, operation: str, pointer: str, value: Any = None) -> Any:
    result = copy.deepcopy(document)
    tokens = [
        token.replace("~1", "/").replace("~0", "~")
        for token in pointer.lstrip("/").split("/")
    ]
    target = result
    for token in tokens[:-1]:
        target = target[int(token)] if isinstance(target, list) else target[token]
    final = tokens[-1]
    key: Any = int(final) if isinstance(target, list) else final
    if operation == "remove":
        del target[key]
    elif operation in {"add", "replace"}:
        target[key] = value
    else:
        raise AssertionError(f"未知变更操作 {operation}")
    return result


def validate_semantics(instance: Any, schema_name: str) -> None:
    if schema_name == "detection-result-v1.schema.json":
        probabilities = instance["class_probabilities"]
        if abs(sum(probabilities.values()) - 1.0) > 1e-9:
            raise ValidationError("probability_sum", "/class_probabilities", "概率和不等于 1")
        geometry_fields = {
            "MASK_REF": {"image_id"},
            "POLYGON": {"points"},
            "BBOX": {"x", "y", "width", "height"},
            "POLAR_INTERVAL": {
                "angle_start_degrees",
                "angle_end_degrees",
                "radial_start",
                "radial_end",
            },
        }
        for index, region in enumerate(instance["regions"]):
            expected = geometry_fields[region["geometry_type"]]
            if set(region["geometry"]) != expected:
                raise ValidationError(
                    "geometry_type",
                    f"/regions/{index}/geometry",
                    f"预期字段 {sorted(expected)}",
                )


def validate_examples(engine: SchemaEngine) -> None:
    mappings = {
        "detection-result-v1.json": "detection-result-v1.schema.json",
        "standard-error-v1.json": "standard-error-v1.schema.json",
        "events/inference-task-v1.json": "inference-task-v1.schema.json",
        "events/outbox-event-v1.json": "outbox-event-v1.schema.json",
        "events/trace-headers-v1.json": "trace-headers-v1.schema.json",
        "state-transitions-v1.json": "state-transition-v1.schema.json",
        "http/write-examples-v1.json": "http-write-examples-v1.schema.json",
        "../consumers/v1-consumers.json": "consumer-migration-r1.schema.json",
    }
    for example_name, schema_name in mappings.items():
        instance = load(CONTRACTS / "examples" / example_name)
        engine.validate_file(instance, CONTRACTS / "json-schema" / schema_name)
        validate_semantics(instance, schema_name)

    cases_path = CONTRACTS / "examples" / "invalid" / "cases-v1.json"
    for case in load(cases_path)["cases"]:
        base = (cases_path.parent / case["base"]).resolve()
        instance = mutate(load(base), case["operation"], case["path"], case.get("value"))
        try:
            engine.validate_file(
                instance, CONTRACTS / "json-schema" / case["schema"]
            )
            validate_semantics(instance, case["schema"])
            if case["schema"] == "state-transition-v1.schema.json":
                validate_transitions(instance)
        except ValidationError as exc:
            if (
                exc.keyword != case["expected_keyword"]
                and case["expected_keyword"] not in str(exc)
            ):
                raise AssertionError(
                    f"{case['case_id']} 失败关键字为 {exc.keyword}，"
                    f"预期 {case['expected_keyword']}"
                ) from exc
        else:
            raise AssertionError(f"非法示例未被拒绝：{case['case_id']}")


TRANSITIONS = {
    "capture": {
        ("CREATED", "UPLOADING"),
        ("UPLOADING", "READY"),
        ("READY", "SUBMITTED"),
        ("SUBMITTED", "PROCESSING"),
        ("PROCESSING", "REVIEW_PENDING"),
    },
    "execution": {("QUEUED", "RUNNING"), ("RUNNING", "SUCCEEDED")},
    "review": {("PENDING", "CLAIMED")},
    "object": {("STAGING", "AVAILABLE")},
    "model": {("APPROVED", "SHADOW")},
}


def validate_transitions(document: Any) -> None:
    for case in document["cases"]:
        actual = (case["from"], case["to"]) in TRANSITIONS[case["domain"]]
        if actual != case["legal"]:
            raise ValidationError(
                "state_transition", f"/cases/{case['case_id']}", "合法性标记与状态机不一致"
            )


def resolve_openapi(schema: Any, document: dict[str, Any]) -> Any:
    while isinstance(schema, dict) and "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            return schema
        current: Any = document
        for token in ref[2:].split("/"):
            current = current[token.replace("~1", "/").replace("~0", "~")]
        schema = current
    return schema


def validate_references(document: Any, document_path: Path) -> None:
    """确认规范中的每个内部或外部引用都能离线解析。"""
    seen: set[tuple[str, str]] = set()

    def walk(value: Any, current_document: Any, current_path: Path) -> None:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str):
                marker = (str(current_path.resolve()), ref)
                if marker not in seen:
                    seen.add(marker)
                    file_part, _, fragment = ref.partition("#")
                    target_path = (
                        (current_path.parent / file_part).resolve()
                        if file_part
                        else current_path.resolve()
                    )
                    target_document = (
                        load(target_path) if file_part else current_document
                    )
                    target = SchemaEngine.pointer(target_document, fragment)
                    walk(target, target_document, target_path)
            for child in value.values():
                walk(child, current_document, current_path)
        elif isinstance(value, list):
            for child in value:
                walk(child, current_document, current_path)

    walk(document, document, document_path)


def assert_strict_object(
    schema: Any,
    document: dict[str, Any],
    operation_id: str,
    document_path: Path | None = None,
    seen: set[tuple[str, str]] | None = None,
) -> None:
    document_path = document_path or CONTRACTS / "openapi" / "tool-defect-api-v1.json"
    seen = seen or set()
    if not isinstance(schema, dict):
        return
    if "$ref" in schema:
        ref = schema["$ref"]
        marker = (str(document_path), ref)
        if marker in seen:
            return
        seen.add(marker)
        if ref.startswith("#/"):
            schema = resolve_openapi(schema, document)
        else:
            file_part, _, fragment = ref.partition("#")
            document_path = (document_path.parent / file_part).resolve()
            document = load(document_path)
            schema = SchemaEngine.pointer(document, fragment)
    if schema.get("type") == "object" and schema.get("additionalProperties") not in (
        False,
    ) and not isinstance(schema.get("additionalProperties"), dict):
        raise AssertionError(f"{operation_id} 请求对象未拒绝未知字段")
    for child in schema.get("properties", {}).values():
        assert_strict_object(child, document, operation_id, document_path, seen)
    if "items" in schema:
        assert_strict_object(schema["items"], document, operation_id, document_path, seen)
    for keyword in ("oneOf", "allOf", "anyOf"):
        for child in schema.get(keyword, []):
            assert_strict_object(child, document, operation_id, document_path, seen)


def validate_openapi() -> None:
    api_path = CONTRACTS / "openapi" / "tool-defect-api-v1.json"
    api = load(api_path)
    validate_references(api, api_path)
    if api.get("openapi") != "3.1.0":
        raise AssertionError("OpenAPI 必须精确为 3.1.0")
    if api.get("jsonSchemaDialect") != "https://json-schema.org/draft/2020-12/schema":
        raise AssertionError("OpenAPI 必须声明 JSON Schema 2020-12 方言")
    expected_paths = {
        "/api/v1/edge/captures",
        "/api/v1/edge/captures/{capture_id}/images/{image_id}/complete",
        "/api/v1/edge/captures/{capture_id}/submit",
        "/api/v1/edge/sync/captures/query",
        "/api/v1/edge/devices/{device_id}/heartbeat",
        "/api/v1/detections",
        "/api/v1/review-tasks",
        "/api/v1/dataset-versions",
        "/api/v1/training-runs",
        "/api/v1/model-deployments",
        "/internal/v1/runtime/ready",
        "/internal/v1/runtime/models",
    }
    missing = expected_paths - set(api["paths"])
    if missing:
        raise AssertionError(f"OpenAPI 缺少核心端点：{sorted(missing)}")

    operations: dict[str, tuple[str, str, dict[str, Any]]] = {}
    writes: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for path, path_item in api["paths"].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            operation_id = operation.get("operationId")
            if not operation_id or operation_id in operations:
                raise AssertionError(f"operationId 缺失或重复：{path} {method}")
            operations[operation_id] = (path, method, operation)
            if method in WRITE_METHODS:
                writes[operation_id] = (path, method, operation)
                if not operation.get("security"):
                    raise AssertionError(f"{operation_id} 缺少安全要求")
                parameters = [
                    resolve_openapi(p, api)
                    for p in path_item.get("parameters", []) + operation.get("parameters", [])
                ]
                headers = {
                    p.get("name") for p in parameters if p.get("in") == "header"
                }
                if "Idempotency-Key" not in headers and "If-Match" not in headers:
                    raise AssertionError(f"{operation_id} 缺少幂等键或条件更新头")
                request_body = operation.get("requestBody")
                if request_body:
                    request_body = resolve_openapi(request_body, api)
                    content = request_body.get("content", {}).get("application/json")
                    if not content:
                        raise AssertionError(f"{operation_id} 写请求缺少 JSON 内容")
                    assert_strict_object(content["schema"], api, operation_id)
                response_codes = set(operation.get("responses", {}))
                for required in {"400", "401", "403", "409", "422"}:
                    if required not in response_codes:
                        raise AssertionError(f"{operation_id} 缺少 {required} 响应")
                if operation.get("x-write-example-operation") != operation_id:
                    raise AssertionError(f"{operation_id} 未绑定写接口示例")

    sidecar = load(CONTRACTS / "examples" / "http" / "write-examples-v1.json")
    indexed = {item["operation_id"]: item for item in sidecar["operations"]}
    if set(indexed) != set(writes):
        raise AssertionError(
            f"写接口示例覆盖不一致：缺少 {sorted(set(writes)-set(indexed))}，"
            f"多余 {sorted(set(indexed)-set(writes))}"
        )
    shared = load(CONTRACTS / "examples" / "http" / "common-responses-v1.json")
    standard_error_schema = CONTRACTS / "json-schema" / "standard-error-v1.schema.json"
    for error_example in shared.values():
        SchemaEngine().validate_file(error_example, standard_error_schema)
    for operation_id, item in indexed.items():
        if set(item["cases"]) != FIVE_CASES:
            raise AssertionError(f"{operation_id} 未提供完整五类示例")
        operation = writes[operation_id][2]
        for case_name, case in item["cases"].items():
            status = str(case["status"])
            if status not in operation["responses"]:
                raise AssertionError(f"{operation_id}/{case_name} 状态码未在 OpenAPI 声明")
        if item.get("success_request", {}) and "requestBody" in operation:
            request_body = resolve_openapi(operation["requestBody"], api)
            schema = request_body["content"]["application/json"]["schema"]
            request_example = item["success_request"]
            if "$example_ref" in request_example:
                request_example = load(
                    (
                        CONTRACTS
                        / "examples"
                        / "http"
                        / request_example["$example_ref"]
                    ).resolve()
                )
            # OpenAPI 模式同样由最小引擎验证；把根文档作为当前文档。
            SchemaEngine().validate(
                request_example,
                resolve_openapi(schema, api),
                CONTRACTS / "openapi" / "tool-defect-api-v1.json",
                "",
            )
            unknown_request = copy.deepcopy(request_example)
            unknown_request["unexpected_field"] = "must-be-rejected"
            try:
                SchemaEngine().validate(
                    unknown_request,
                    resolve_openapi(schema, api),
                    CONTRACTS / "openapi" / "tool-defect-api-v1.json",
                    "",
                )
            except ValidationError as exc:
                if exc.keyword != "additionalProperties":
                    raise AssertionError(
                        f"{operation_id} 未以未知字段规则拒绝额外字段"
                    ) from exc
            else:
                raise AssertionError(f"{operation_id} 接受了未知请求字段")
        success_status = str(item["cases"]["success"]["status"])
        response = resolve_openapi(operation["responses"][success_status], api)
        response_content = response.get("content", {}).get("application/json")
        if response_content and item.get("success_response") is not None:
            SchemaEngine().validate(
                item["success_response"],
                resolve_openapi(response_content["schema"], api),
                CONTRACTS / "openapi" / "tool-defect-api-v1.json",
                "",
            )
        for error_name in ("conflict", "forbidden", "validation"):
            if f"errors.{error_name}" not in shared:
                raise AssertionError(f"共享错误示例缺少 {error_name}")


def validate_asyncapi(engine: SchemaEngine) -> None:
    api_path = CONTRACTS / "asyncapi" / "inference-events-v1.json"
    api = load(api_path)
    validate_references(api, api_path)
    if api.get("asyncapi") != "3.0.0":
        raise AssertionError("AsyncAPI 必须精确为 3.0.0")
    semantics = api.get("x-delivery-semantics", {})
    expected = {
        "delivery_guarantee": "at-least-once",
        "consumer_acknowledgement": "manual",
        "queue_type": "quorum",
        "business_effect": "at-most-once-by-inbox",
    }
    for key, value in expected.items():
        if semantics.get(key) != value:
            raise AssertionError(f"AsyncAPI 投递语义 {key} 应为 {value}")
    if not semantics.get("deduplication_keys"):
        raise AssertionError("AsyncAPI 缺少去重键")
    if api.get("x-tracing", {}).get("header") != "traceparent":
        raise AssertionError("AsyncAPI 必须要求 traceparent")
    if not semantics.get("queue_durable") or not semantics.get("message_persistent"):
        raise AssertionError("AsyncAPI 必须声明持久队列和持久消息")
    if not semantics.get("publisher_confirms"):
        raise AssertionError("AsyncAPI 必须启用发布确认")
    if semantics.get("dead_letter_auto_replay") is not False:
        raise AssertionError("死信不得自动回灌")
    exchange = (
        api["channels"]["inferenceTasks"]
        .get("bindings", {})
        .get("amqp", {})
        .get("exchange", {})
    )
    if not exchange.get("durable"):
        raise AssertionError("推理交换器必须持久化")
    examples = {
        "inference-task-v1.json": "inference-task-v1.schema.json",
        "outbox-event-v1.json": "outbox-event-v1.schema.json",
    }
    for example_name, schema_name in examples.items():
        engine.validate_file(
            load(CONTRACTS / "examples" / "events" / example_name),
            CONTRACTS / "json-schema" / schema_name,
        )


def validate_consumers() -> None:
    manifest = load(CONTRACTS / "consumers" / "v1-consumers.json")
    api = load(CONTRACTS / "openapi" / "tool-defect-api-v1.json")
    asyncapi = load(CONTRACTS / "asyncapi" / "inference-events-v1.json")
    http_operations = {
        operation["operationId"]
        for item in api["paths"].values()
        for method, operation in item.items()
        if method in HTTP_METHODS
    }
    event_operations = set(asyncapi["operations"])
    consumers = {item["consumer_id"]: item for item in manifest["consumers"]}
    expected = {"edge-agent", "business-api", "inference-service", "web-console"}
    if set(consumers) != expected:
        raise AssertionError("消费者契约必须精确覆盖四个跨进程应用")
    for consumer in consumers.values():
        unknown_http = set(consumer["http_operations"]) - http_operations
        unknown_events = set(consumer["event_operations"]) - event_operations
        if unknown_http or unknown_events:
            raise AssertionError(
                f"{consumer['consumer_id']} 引用未知操作："
                f"{sorted(unknown_http | unknown_events)}"
            )


V2_EXPECTED_PATHS = {
    "/api/v2/capabilities/manual-detection",
    "/api/v2/detection-batches",
    "/api/v2/detection-batches/{batch_id}",
    "/api/v2/detection-batches/{batch_id}/items",
    "/api/v2/detection-batches/{batch_id}/items/{item_id}",
    "/api/v2/detection-batches/{batch_id}/items/{item_id}/complete",
    "/api/v2/detection-batches/{batch_id}/items/{item_id}/renew",
    "/api/v2/detection-batches/{batch_id}/submit",
    "/api/v2/detection-batches/{batch_id}/items/{item_id}/quick-review",
    "/api/v2/production/detection-items",
    "/api/v2/admin/detection-items",
    "/api/v2/admin/detection-items/{item_id}/feedback",
    "/api/v2/sample-candidates",
    "/api/v2/sample-candidates/{candidate_id}/decision",
    "/api/v2/sample-exports",
    "/api/v2/sample-exports/{export_job_id}",
    "/api/v2/sample-exports/{export_job_id}/download-ticket",
    "/api/v2/model-upload-sessions",
    "/api/v2/model-upload-sessions/{upload_id}",
    "/api/v2/model-upload-sessions/{upload_id}/complete",
    "/api/v2/model-versions",
    "/api/v2/model-versions/{model_version_id}/activation-requests",
    "/api/v2/model-activation-requests/{request_id}/approve",
    "/api/v2/model-versions/{model_version_id}/rollback-requests",
}


def validate_openapi_v2() -> tuple[set[str], set[str]]:
    api_path = CONTRACTS / "openapi" / "tool-defect-api-v2.json"
    api = load(api_path)
    validate_references(api, api_path)
    if api.get("openapi") != "3.1.0" or api.get("info", {}).get("version") != "2.0.0":
        raise AssertionError("第二版 OpenAPI 版本必须为 3.1.0 / 2.0.0")
    if set(api.get("paths", {})) != V2_EXPECTED_PATHS:
        raise AssertionError(
            f"第二版 OpenAPI 路径不完整：缺少 {sorted(V2_EXPECTED_PATHS-set(api.get('paths', {})))}"
        )
    operations: set[str] = set()
    writes: set[str] = set()
    for path, path_item in api["paths"].items():
        if not path.startswith("/api/v2/"):
            raise AssertionError(f"第二版接口越过 /api/v2：{path}")
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            operation_id = operation.get("operationId")
            if not operation_id or operation_id in operations:
                raise AssertionError(f"第二版 operationId 缺失或重复：{method} {path}")
            operations.add(operation_id)
            if method not in WRITE_METHODS:
                continue
            writes.add(operation_id)
            if operation.get("x-write-example-operation") != operation_id:
                raise AssertionError(f"{operation_id} 未登记写接口示例")
            if not operation.get("security"):
                raise AssertionError(f"{operation_id} 缺少安全要求")
            parameters = [
                resolve_openapi(value, api)
                for value in path_item.get("parameters", []) + operation.get("parameters", [])
            ]
            headers = {value.get("name") for value in parameters if value.get("in") == "header"}
            if not ({"Idempotency-Key", "If-Match"} & headers):
                raise AssertionError(f"{operation_id} 缺少幂等或条件更新头")
            required_responses = {"400", "401", "403", "409", "410", "422"}
            missing = required_responses - set(operation.get("responses", {}))
            if missing:
                raise AssertionError(f"{operation_id} 缺少响应 {sorted(missing)}")
            request_body = operation.get("requestBody")
            if request_body:
                request_body = resolve_openapi(request_body, api)
                schema = request_body["content"]["application/json"]["schema"]
                assert_strict_object(schema, api, operation_id, api_path)

    sidecar = load(CONTRACTS / "examples" / "http" / "write-examples-v2.json")
    indexed = {item["operation_id"]: item for item in sidecar["operations"]}
    if set(indexed) != writes:
        raise AssertionError(
            f"第二版写示例覆盖不一致：缺少 {sorted(writes-set(indexed))}，多余 {sorted(set(indexed)-writes)}"
        )
    required_cases = {"duplicate", "conflict", "unauthorized", "validation_error", "invalid_state", "retired"}
    if set(sidecar.get("shared_cases", {})) != required_cases:
        raise AssertionError("第二版写示例必须覆盖重复、冲突、未授权、校验、非法状态和退役")
    if sidecar["shared_cases"]["retired"] != {
        "status": 410, "error_code": "TD-LEGACY-FEATURE-RETIRED", "retryable": False, "creates_task": False
    }:
        raise AssertionError("退役示例必须为 410 且不得创建任务")
    for operation_id, example in indexed.items():
        operation = next(
            operation
            for item in api["paths"].values()
            for method, operation in item.items()
            if method in HTTP_METHODS and operation["operationId"] == operation_id
        )
        if str(example["success_status"]) not in operation["responses"]:
            raise AssertionError(f"{operation_id} 成功示例状态未在 OpenAPI 声明")
    return operations, writes


V2_TRANSITIONS = {
    "batch": {("DRAFT", "READY"), ("READY", "PROCESSING"), ("PROCESSING", "PARTIALLY_COMPLETED")},
    "item": {("READY", "QUEUED"), ("PROCESSING", "QUALITY_REJECTED")},
    "export": {("RUNNING", "SUCCEEDED")},
    "model_upload": {("UPLOADED", "VALIDATING")},
}


def validate_transitions_v2() -> None:
    document = load(CONTRACTS / "examples" / "state-transitions-v2.json")
    legal_and_illegal: dict[str, set[bool]] = {}
    for case in document["cases"]:
        actual = (case["from"], case["to"]) in V2_TRANSITIONS.get(case["domain"], set())
        if actual != case["legal"]:
            raise AssertionError(f"第二版非法状态示例标记错误：{case['case_id']}")
        legal_and_illegal.setdefault(case["domain"], set()).add(case["legal"])
    if any(values != {True, False} for values in legal_and_illegal.values()):
        raise AssertionError("每个第二版状态域必须同时包含正例和反例")


def validate_asyncapi_v2(engine: SchemaEngine) -> set[str]:
    api_path = CONTRACTS / "asyncapi" / "inference-events-v2.json"
    api = load(api_path)
    validate_references(api, api_path)
    if api.get("asyncapi") != "3.0.0" or api.get("info", {}).get("version") != "2.0.0":
        raise AssertionError("第二版 AsyncAPI 版本必须为 3.0.0 / 2.0.0")
    expected_addresses = {
        "tool_defect.inference.item.requested.v2", "tool_defect.inference.item.completed.v2",
        "tool_defect.inference.item.failed.v2", "tool_defect.sample.export.requested.v2",
        "tool_defect.sample.export.completed.v2", "tool_defect.model.validation.requested.v2",
        "tool_defect.model.validation.completed.v2",
    }
    actual_addresses = {channel["address"] for channel in api["channels"].values()}
    if actual_addresses != expected_addresses:
        raise AssertionError("第二版事件集合不完整")
    semantics = api.get("x-delivery-semantics", {})
    for key, expected in {
        "delivery_guarantee": "at-least-once", "consumer_acknowledgement": "manual",
        "queue_type": "quorum", "business_effect": "at-most-once-by-inbox",
    }.items():
        if semantics.get(key) != expected:
            raise AssertionError(f"第二版事件投递语义 {key} 错误")
    schema_path = CONTRACTS / "json-schema" / "event-payloads-v2.schema.json"
    schema_document = load(schema_path)
    examples = load(CONTRACTS / "examples" / "events" / "events-v2.json")
    seen_messages: set[str] = set()
    for item in examples["events"]:
        name = item["message"]
        seen_messages.add(name)
        schema = schema_document["$defs"][name]
        engine.validate(item["payload"], schema, schema_path, "")
        invalid = copy.deepcopy(item["payload"])
        invalid[item["invalid_field"]] = "must-be-rejected"
        try:
            engine.validate(invalid, schema, schema_path, "")
        except ValidationError as exc:
            if exc.keyword != "additionalProperties":
                raise
        else:
            raise AssertionError(f"第二版事件反例未被拒绝：{name}")
    if seen_messages != set(api["components"]["messages"]):
        raise AssertionError("第二版事件正反例未覆盖全部消息")
    return set(api["operations"])


def validate_consumers_v2(http_operations: set[str], event_operations: set[str]) -> None:
    engine = SchemaEngine()
    engine.validate_file(
        load(CONTRACTS / "consumers" / "v1-consumers.json"),
        CONTRACTS / "json-schema" / "consumer-migration-r1.schema.json",
    )
    engine.validate_file(
        load(CONTRACTS / "consumers" / "v2-consumers.json"),
        CONTRACTS / "json-schema" / "consumer-contract-v2.schema.json",
    )
    manifest = load(CONTRACTS / "consumers" / "v2-consumers.json")
    registered_http = set()
    registered_events = set()
    for consumer in manifest["consumers"]:
        registered_http.update(consumer["http_operations"])
        registered_events.update(consumer["event_operations"])
        if consumer["migration_status"] == "ACTIVE":
            raise AssertionError("R1 不得把尚未接入的第二版消费者标为 ACTIVE")
    if registered_http != http_operations:
        raise AssertionError(f"第二版 HTTP 消费者登记漂移：{sorted(http_operations-registered_http)}")
    if registered_events != event_operations:
        raise AssertionError(f"第二版事件消费者登记漂移：{sorted(event_operations-registered_events)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    engine = SchemaEngine()
    for path in sorted(CONTRACTS.rglob("*.json")):
        load(path)
    validate_examples(engine)
    validate_transitions(load(CONTRACTS / "examples" / "state-transitions-v1.json"))
    validate_openapi()
    validate_asyncapi(engine)
    validate_consumers()
    http_v2, _writes_v2 = validate_openapi_v2()
    validate_transitions_v2()
    events_v2 = validate_asyncapi_v2(engine)
    validate_consumers_v2(http_v2, events_v2)
    print("契约验证通过：v1/v2 模式、示例、状态机、OpenAPI、AsyncAPI 与消费者清单")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, ValidationError) as exc:
        print(f"契约验证失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
