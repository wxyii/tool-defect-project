package com.tooldefect.business.detectionbatch.infrastructure;

import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import com.tooldefect.business.shared.application.BusinessMessageHandler;
import com.tooldefect.business.shared.application.NonRetryableMessageException;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Component
@ConditionalOnProperty(name="td.messaging.consumer.enabled", havingValue="true")
public final class R4InferenceResultHandler implements BusinessMessageHandler {
    private static final Set<String> COMPLETED_FIELDS=Set.of(
        "message_id","occurred_at","idempotency_key","traceparent","batch_item_id",
        "detection_task_id","attempt_id","quality","algorithm_outcome","result_reference");
    private static final Set<String> FAILED_REQUIRED=Set.of(
        "message_id","occurred_at","idempotency_key","traceparent","batch_item_id",
        "detection_task_id","attempt_id","error_code","retryable");
    private static final Set<String> FAILED_ALLOWED=Set.of(
        "message_id","occurred_at","idempotency_key","traceparent","batch_item_id",
        "detection_task_id","attempt_id","error_code","retryable","safe_detail");
    private static final Set<String> CHECK_TYPES=Set.of(
        "DECODABLE","BLADE_PRESENT","BLADE_COMPLETE","BLUR","EXPOSURE");
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;

    public R4InferenceResultHandler(JdbcTemplate jdbc,ObjectMapper json){
        this.jdbc=java.util.Objects.requireNonNull(jdbc);
        this.json=java.util.Objects.requireNonNull(json);
    }

    @Override
    public void handle(String payloadJson) {
        try {
            JsonNode root=json.readTree(payloadJson);
            if(root.has("quality"))handleCompleted(root);else handleFailed(root);
        } catch (NonRetryableMessageException error) {
            throw error;
        } catch (RuntimeException error) {
            throw new NonRetryableMessageException("第二版推理结果不符合冻结契约",error);
        }
    }

    private void handleCompleted(JsonNode root){
        exact(root,COMPLETED_FIELDS,COMPLETED_FIELDS,"第二版完成事件");
        UUID message=uuid(root,"message_id"), task=uuid(root,"detection_task_id");
        UUID item=uuid(root,"batch_item_id"), attempt=uuid(root,"attempt_id");
        verifyTask(task,item); ensureNoConflictingTerminal(task,message);
        JsonNode quality=root.path("quality");
        exact(quality,Set.of("overall","checker_version","checks"),
            Set.of("overall","checker_version","checks"),"质量结果");
        String overall=text(quality,"overall");
        if(!Set.of("ACCEPTED","WARNING","REJECTED").contains(overall))invalid("质量总体状态非法");
        UUID qualityId=stable("quality:"+item+":"+text(quality,"checker_version"));
        jdbc.update("""
            INSERT INTO image_quality_result_v2(quality_result_id,batch_item_id,overall,checker_version)
            VALUES (?,?,?,?) ON CONFLICT (batch_item_id,checker_version) DO NOTHING
            """,qualityId,item,overall,text(quality,"checker_version"));
        JsonNode checks=quality.path("checks");
        if(!checks.isArray()||checks.isEmpty()||checks.size()>20)invalid("质量检查数组非法");
        Set<String> seen=new HashSet<>();
        for(JsonNode check:checks){
            exact(check,Set.of("check_type","status","rule_id","reason_code","user_hint"),
                Set.of("check_type","status","rule_id","reason_code","measurement","threshold","user_hint"),"质量检查");
            String type=text(check,"check_type");
            if(!CHECK_TYPES.contains(type)||!seen.add(type))invalid("质量检查类型缺失或重复");
            String status=text(check,"status");
            if(!Set.of("PASS","WARNING","FAIL","NOT_RUN").contains(status))invalid("质量检查状态非法");
            jdbc.update("""
                INSERT INTO image_quality_check_v2(quality_check_id,quality_result_id,check_type,
                  status,rule_id,reason_code,measurement,threshold,user_hint)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT (quality_result_id,check_type) DO NOTHING
                """,stable("check:"+qualityId+":"+type),qualityId,type,status,text(check,"rule_id"),
                text(check,"reason_code"),numberOrNull(check,"measurement"),
                numberOrNull(check,"threshold"),text(check,"user_hint"));
        }
        JsonNode reference=root.path("result_reference");
        exact(reference,Set.of("bucket","object_key","sha256","size_bytes","media_type"),
            Set.of("bucket","object_key","object_version","sha256","size_bytes","media_type"),"结果对象引用");
        String outcome=text(root,"algorithm_outcome");
        if(!Set.of("QUALIFIED","UNQUALIFIED","INCONCLUSIVE").contains(outcome))invalid("算法结论非法");
        boolean rejected="REJECTED".equals(overall);
        jdbc.update("""
            INSERT INTO detection_item_result_v2(detection_task_id,batch_item_id,message_id,
              attempt_id,terminal_kind,algorithm_outcome,result_bucket,result_object_key,
              result_object_version,result_sha256,result_size_bytes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,task,item,message,attempt,rejected?"QUALITY_REJECTED":"COMPLETED",outcome,
            text(reference,"bucket"),text(reference,"object_key"),optionalText(reference,"object_version"),
            sha256(reference,"sha256"),positiveLong(reference,"size_bytes"));
        jdbc.update("UPDATE detection_task_v2 SET status='SUCCEEDED',updated_at=now(),record_version=record_version+1 WHERE detection_task_id=?",task);
        jdbc.update("UPDATE detection_batch_item_v2 SET status=?,algorithm_outcome=?,updated_at=now(),record_version=record_version+1 WHERE batch_item_id=?",
            rejected?"QUALITY_REJECTED":"COMPLETED",rejected?null:outcome,item);
    }

    private void handleFailed(JsonNode root){
        exact(root,FAILED_REQUIRED,FAILED_ALLOWED,"第二版失败事件");
        UUID message=uuid(root,"message_id"),task=uuid(root,"detection_task_id");
        UUID item=uuid(root,"batch_item_id"),attempt=uuid(root,"attempt_id");
        verifyTask(task,item);ensureNoConflictingTerminal(task,message);
        String code=text(root,"error_code");
        if(!code.matches("^TD-[A-Z0-9-]+$"))invalid("失败码非法");
        JsonNode retry=root.path("retryable");
        if(!retry.isBoolean())invalid("retryable 必须为布尔值");
        jdbc.update("""
            INSERT INTO detection_item_result_v2(detection_task_id,batch_item_id,message_id,
              attempt_id,terminal_kind,error_code,retryable) VALUES (?,?,?,?,'FAILED',?,?)
            """,task,item,message,attempt,code,retry.booleanValue());
        jdbc.update("UPDATE detection_task_v2 SET status='FAILED',updated_at=now(),record_version=record_version+1 WHERE detection_task_id=?",task);
        jdbc.update("UPDATE detection_batch_item_v2 SET status='FAILED',algorithm_outcome=NULL,updated_at=now(),record_version=record_version+1 WHERE batch_item_id=?",item);
    }

    private void verifyTask(UUID task,UUID item){
        Integer count=jdbc.queryForObject("SELECT count(*) FROM detection_task_v2 WHERE detection_task_id=? AND batch_item_id=?",Integer.class,task,item);
        if(count==null||count!=1)invalid("推理结果任务与图片项不匹配");
    }
    private void ensureNoConflictingTerminal(UUID task,UUID message){
        var rows=jdbc.query("SELECT message_id FROM detection_item_result_v2 WHERE detection_task_id=?",
            (row,n)->row.getObject("message_id",UUID.class),task);
        if(!rows.isEmpty()&&!rows.getFirst().equals(message))invalid("同一逻辑任务收到冲突终态");
    }
    private static void exact(JsonNode node,Set<String> required,Set<String> allowed,String name){
        if(!node.isObject())invalid(name+"必须为对象");
        Set<String> actual=new HashSet<>();node.properties().forEach(entry->actual.add(entry.getKey()));
        if(!actual.containsAll(required)||!allowed.containsAll(actual))invalid(name+"字段不符合冻结契约");
    }
    private static String text(JsonNode node,String field){String value=node.path(field).asString(null);if(value==null)invalid(field+"必须为字符串");return value;}
    private static String optionalText(JsonNode node,String field){JsonNode value=node.path(field);return value.isMissingNode()?null:text(node,field);}
    private static UUID uuid(JsonNode node,String field){try{return UUID.fromString(text(node,field));}catch(IllegalArgumentException error){invalid(field+"不是 UUID");return null;}}
    private static String sha256(JsonNode node,String field){String value=text(node,field);if(!value.matches("[0-9a-f]{64}"))invalid(field+"不是 SHA-256");return value;}
    private static long positiveLong(JsonNode node,String field){JsonNode value=node.path(field);if(!value.isIntegralNumber()||value.longValue()<1)invalid(field+"不是正整数");return value.longValue();}
    private static Double numberOrNull(JsonNode node,String field){JsonNode value=node.path(field);if(value.isMissingNode())return null;if(!value.isNumber()||!Double.isFinite(value.doubleValue()))invalid(field+"不是有限数字");return value.doubleValue();}
    private static UUID stable(String value){return UUID.nameUUIDFromBytes(value.getBytes(StandardCharsets.UTF_8));}
    private static void invalid(String message){throw new NonRetryableMessageException(message);}
}
