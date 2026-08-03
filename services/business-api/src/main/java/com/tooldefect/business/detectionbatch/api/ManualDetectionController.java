package com.tooldefect.business.detectionbatch.api;

import static com.tooldefect.business.shared.api.ContractValues.*;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import com.tooldefect.business.detectionbatch.application.ManualDetectionBatchService;
import com.tooldefect.business.detectionbatch.application.ManualDetectionViolation;
import com.tooldefect.business.detectionbatch.application.ManualDetectionViolation.Kind;
import com.tooldefect.business.identity.application.LocalIdentity;

@RestController
@RequestMapping("/api/v2")
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
public final class ManualDetectionController {
    private static final Set<String> CREATE_FIELDS=Set.of("usage_stage","usage_stage_note");
    private static final Set<String> ITEM_FIELDS=Set.of("file_name","size_bytes","media_type","sha256");
    private static final Set<String> COMPLETE_FIELDS=Set.of("sha256","size_bytes");
    private static final Set<String> SUBMIT_FIELDS=Set.of("expected_version");
    private static final Set<String> QUICK_REVIEW_FIELDS=Set.of("decision","supersedes_record_id");
    private static final Set<String> QUICK_REVIEW_DECISIONS=Set.of(
        "DEFECT_CONFIRMED","NO_DEFECT_CONFIRMED","UNABLE_TO_DETERMINE");
    private static final Set<String> STAGES=Set.of("NEW_BLADE","AFTER_ONE_WHEEL","AFTER_TWO_WHEELS","AFTER_THREE_WHEELS","OTHER","UNSPECIFIED");
    private final ManualDetectionBatchService service;
    public ManualDetectionController(ManualDetectionBatchService service){this.service=java.util.Objects.requireNonNull(service);}

    @GetMapping("/capabilities/manual-detection")
    Map<String,Object> capabilities(Authentication authentication){identity(authentication);return service.capabilities();}

    @PostMapping("/detection-batches")
    ResponseEntity<Map<String,Object>> create(@RequestHeader("Idempotency-Key") String key,
            @RequestBody Map<String,Object> body,Authentication authentication,HttpServletRequest servlet){
        var request=object(body,CREATE_FIELDS,"创建批次请求");
        var response=service.create(identity(authentication).userId(),key,oneOf(request,"usage_stage",STAGES),
            request.containsKey("usage_stage_note")?text(request,"usage_stage_note",1,200):null,
            request,requestId(servlet),traceId(servlet));
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/detection-batches/{batch_id}/items")
    ResponseEntity<Map<String,Object>> add(@PathVariable("batch_id") UUID batchId,
            @RequestHeader("Idempotency-Key") String key,@RequestBody Map<String,Object> body,
            Authentication authentication,HttpServletRequest servlet){
        var request=object(body,ITEM_FIELDS,"新增图片项请求");
        var response=service.addItem(identity(authentication).userId(),batchId,key,text(request,"file_name",1,255),
            integer(request,"size_bytes",1,Long.MAX_VALUE),oneOf(request,"media_type",Set.of("image/jpeg","image/png")),
            sha256(request,"sha256"),request,requestId(servlet),traceId(servlet));
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/detection-batches/{batch_id}/items/{item_id}/complete")
    ResponseEntity<Map<String,Object>> complete(@PathVariable("batch_id") UUID batchId,@PathVariable("item_id") UUID itemId,
            @RequestHeader("Idempotency-Key") String key,@RequestBody Map<String,Object> body,
            Authentication authentication,HttpServletRequest servlet){
        var request=object(body,COMPLETE_FIELDS,"上传确认请求");
        var response=service.complete(identity(authentication).userId(),batchId,itemId,key,sha256(request,"sha256"),
            integer(request,"size_bytes",1,Long.MAX_VALUE),request,requestId(servlet),traceId(servlet));
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/detection-batches/{batch_id}/submit")
    ResponseEntity<Map<String,Object>> submit(@PathVariable("batch_id") UUID batchId,@RequestHeader("Idempotency-Key") String key,
            @RequestBody Map<String,Object> body,Authentication authentication,HttpServletRequest servlet){
        var request=object(body,SUBMIT_FIELDS,"批次提交请求");
        var response=service.submit(identity(authentication).userId(),batchId,key,
            integer(request,"expected_version",1,Long.MAX_VALUE),request,requestId(servlet),traceId(servlet));
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @DeleteMapping("/detection-batches/{batch_id}/items/{item_id}")
    ResponseEntity<Void> delete(@PathVariable("batch_id") UUID batchId,@PathVariable("item_id") UUID itemId,
            @RequestHeader("If-Match") String ifMatch,Authentication authentication,HttpServletRequest servlet){
        long version;
        try{version=Long.parseLong(ifMatch.replace("\"",""));}
        catch(RuntimeException invalid){throw new ManualDetectionViolation(Kind.INTEGRITY,"If-Match 不合法");}
        service.delete(identity(authentication).userId(),batchId,itemId,version,requestId(servlet),traceId(servlet));
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/detection-batches")
    Map<String,Object> list(@RequestParam(required=false) String cursor,Authentication authentication){
        var user=identity(authentication);return service.list(user.userId(),canReadAll(user),cursor);
    }
    @GetMapping("/detection-batches/{batch_id}")
    Map<String,Object> getBatch(@PathVariable("batch_id") UUID batchId,Authentication authentication){
        var user=identity(authentication);return service.getBatch(user.userId(),canReadAll(user),batchId);
    }
    @GetMapping("/detection-batches/{batch_id}/items/{item_id}")
    Map<String,Object> getItem(@PathVariable("batch_id") UUID batchId,@PathVariable("item_id") UUID itemId,Authentication authentication){
        var user=identity(authentication);return service.getItem(user.userId(),canReadAll(user),batchId,itemId);
    }

    @PutMapping("/detection-batches/{batch_id}/items/{item_id}/quick-review")
    ResponseEntity<Map<String,Object>> quickReview(@PathVariable("batch_id") UUID batchId,
            @PathVariable("item_id") UUID itemId,
            @RequestHeader("Idempotency-Key") String key,
            @RequestBody Map<String,Object> body, Authentication authentication,
            HttpServletRequest servlet) {
        var request=object(body,QUICK_REVIEW_FIELDS,"快速反馈请求");
        var user=identity(authentication);
        UUID supersedes=null;
        if(request.containsKey("supersedes_record_id")){
            try{supersedes=UUID.fromString(text(request,"supersedes_record_id",36,36));}
            catch(RuntimeException invalid){throw new ManualDetectionViolation(Kind.INTEGRITY,"修订记录标识不合法");}
        }
        var response=service.saveQuickReview(user.userId(),canReadAll(user),batchId,itemId,
            key,oneOf(request,"decision",QUICK_REVIEW_DECISIONS),supersedes,request,
            requestId(servlet),traceId(servlet));
        return ResponseEntity.status(response.status()).body(response.body());
    }

    private static LocalIdentity identity(Authentication auth){
        if(auth==null||!(auth.getPrincipal() instanceof LocalIdentity value))throw new ManualDetectionViolation(Kind.DENIED,"缺少人员身份");
        return value;
    }
    private static boolean canReadAll(LocalIdentity user){return user.permissions().contains("manual-detection:read:all");}
    private static String requestId(HttpServletRequest request){try{return UUID.fromString(request.getHeader("X-Request-Id")).toString();}catch(RuntimeException invalid){return UUID.randomUUID().toString();}}
    private static String traceId(HttpServletRequest request){String value=request.getHeader("traceparent");return value!=null&&value.matches("^00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}$")?value.substring(3,35):UUID.randomUUID().toString().replace("-","");}
}
