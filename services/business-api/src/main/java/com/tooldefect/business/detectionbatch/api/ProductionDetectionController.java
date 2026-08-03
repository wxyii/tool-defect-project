package com.tooldefect.business.detectionbatch.api;

import static com.tooldefect.business.shared.api.ContractValues.*;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import com.tooldefect.business.detectionbatch.application.ProductionDetectionRepository;
import com.tooldefect.business.detectionbatch.application.ProductionDetectionService;
import com.tooldefect.business.shared.api.ContractValues.ContractInputViolation;

@RestController
@RequestMapping("/api/v2/production")
@ConditionalOnProperty(name="td.storage.enabled", havingValue="true")
public final class ProductionDetectionController {
    private static final Set<String> REQUEST_FIELDS=Set.of("capture_id","image");
    private static final Set<String> IMAGE_REQUIRED=Set.of("bucket","object_key","sha256","size_bytes","media_type");
    private static final Set<String> IMAGE_ALLOWED=Set.of("bucket","object_key","object_version","sha256","size_bytes","media_type");
    private final ProductionDetectionService service;

    public ProductionDetectionController(ProductionDetectionService service){this.service=java.util.Objects.requireNonNull(service);}

    @PostMapping("/detection-items")
    ResponseEntity<Map<String,Object>> create(@RequestHeader("Idempotency-Key") String key,
            @RequestBody Map<String,Object> body, Authentication authentication,
            HttpServletRequest servlet) {
        var request=object(body,REQUEST_FIELDS,"产线单项请求");
        var image=optionalObject(request.get("image"));
        var source=new ProductionDetectionRepository.Image(
            text(image,"bucket",1,63), text(image,"object_key",1,1024),
            image.containsKey("object_version")?text(image,"object_version",1,200):null,
            sha256(image,"sha256"), integer(image,"size_bytes",1,Long.MAX_VALUE),
            oneOf(image,"media_type",Set.of("image/jpeg","image/png")),0,0);
        String subject=authentication==null?null:authentication.getName();
        if(subject==null||subject.isBlank())throw new ContractInputViolation("缺少设备身份");
        var response=service.create(uuid(request,"capture_id"),subject,source,key,request,traceparent(servlet));
        return ResponseEntity.status(response.status()).body(response.body());
    }

    private static Map<String,Object> optionalObject(Object value){
        if(!(value instanceof Map<?,?> raw))throw new ContractInputViolation("image 必须是对象");
        Map<String,Object> result=new LinkedHashMap<>();
        for(var entry:raw.entrySet()){
            if(!(entry.getKey() instanceof String name))throw new ContractInputViolation("image 键非法");
            result.put(name,entry.getValue());
        }
        if(!result.keySet().containsAll(IMAGE_REQUIRED)||!IMAGE_ALLOWED.containsAll(result.keySet()))
            throw new ContractInputViolation("image 字段与第二版契约不一致");
        return result;
    }

    private static String traceparent(HttpServletRequest request){
        String value=request.getHeader("traceparent");
        if(value!=null&&value.matches("^00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}$"))return value;
        String seed=UUID.randomUUID().toString().replace("-","");
        return "00-"+seed+"-"+seed.substring(0,16)+"-01";
    }
}
