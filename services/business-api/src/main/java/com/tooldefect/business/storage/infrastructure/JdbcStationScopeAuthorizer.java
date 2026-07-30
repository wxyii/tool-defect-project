package com.tooldefect.business.storage.infrastructure;

import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import com.tooldefect.business.storage.application.StationScopeAuthorizer;

@Component
public class JdbcStationScopeAuthorizer implements StationScopeAuthorizer {
    private final JdbcTemplate jdbc;

    public JdbcStationScopeAuthorizer(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public boolean mayWrite(UUID actorStationId, UUID objectStationId) {
        if (actorStationId == null || !actorStationId.equals(objectStationId)) {
            return false;
        }
        Boolean exists = jdbc.queryForObject(
            """
            SELECT EXISTS (
                SELECT 1
                FROM station
                WHERE station_id = ?
                  AND status = 'ACTIVE'
            )
            """,
            Boolean.class,
            actorStationId
        );
        return Boolean.TRUE.equals(exists);
    }

    @Override
    public boolean mayRead(String actorId, UUID imageId, String purpose) {
        String permission = "DOWNLOAD".equals(purpose)
            ? "image:original:download"
            : "image:view";
        Boolean allowed = jdbc.queryForObject(
            """
            SELECT EXISTS (
                SELECT 1
                FROM sys_user user_account
                JOIN sys_user_role user_role
                  ON user_role.user_id = user_account.user_id
                JOIN sys_role_permission role_permission
                  ON role_permission.role_id = user_role.role_id
                JOIN sys_permission permission
                  ON permission.permission_id = role_permission.permission_id
                JOIN sys_scope_binding scope_binding
                  ON (
                    (
                      scope_binding.subject_type = 'USER'
                      AND scope_binding.subject_id = user_account.user_id
                    )
                    OR (
                      scope_binding.subject_type = 'ROLE'
                      AND scope_binding.subject_id = user_role.role_id
                    )
                  )
                JOIN image_object image
                  ON image.image_id = ?
                JOIN capture_event capture
                  ON capture.capture_id = image.capture_id
                JOIN station station_record
                  ON station_record.station_id = capture.station_id
                JOIN production_line line_record
                  ON line_record.line_id = station_record.line_id
                WHERE user_account.external_subject = ?
                  AND user_account.status = 'ACTIVE'
                  AND permission.permission_code = ?
                  AND image.state = 'AVAILABLE'
                  AND (
                    scope_binding.scope_type = 'STATION'
                      AND scope_binding.scope_id = station_record.station_id
                    OR scope_binding.scope_type = 'LINE'
                      AND scope_binding.scope_id = line_record.line_id
                    OR scope_binding.scope_type = 'ORGANIZATION'
                      AND scope_binding.scope_id = line_record.organization_id
                  )
                  AND (? <> 'DOWNLOAD' OR image.kind = 'RAW')
            )
            """,
            Boolean.class,
            imageId,
            actorId,
            permission,
            purpose
        );
        return Boolean.TRUE.equals(allowed);
    }
}
