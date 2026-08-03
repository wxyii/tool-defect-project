package com.tooldefect.business.identity.application;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.crypto.argon2.Argon2PasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.audit.application.AuditTrail;
import com.tooldefect.business.audit.domain.AuditRecord;

@Service
public class LocalIdentityService implements ApplicationRunner {
    private static final Set<String> PERSON_ROLES = Set.of(
        "PRODUCTION_EMPLOYEE", "ADMINISTRATOR"
    );
    private static final Set<String> LEGACY_HIGH_PRIVILEGE_ROLES = Set.of(
        "REVIEWER", "QUALITY_MANAGER", "ALGORITHM_ENGINEER",
        "MODEL_APPROVER", "SYSTEM_OPERATOR", "SECURITY_ADMIN", "AUDITOR"
    );
    private static final Duration IDLE = Duration.ofMinutes(30);
    private static final Duration ABSOLUTE = Duration.ofHours(8);
    private static final Duration FAILURE_WINDOW = Duration.ofMinutes(15);
    private static final Pattern USERNAME =
        Pattern.compile("^[a-z0-9][a-z0-9._-]{2,63}$");
    private static final SecureRandom RANDOM = new SecureRandom();

    private final JdbcTemplate jdbc;
    private final AuditTrail audit;
    private final PasswordEncoder passwords =
        Argon2PasswordEncoder.defaultsForSpringSecurity_v5_8();
    private final String dummyHash = passwords.encode("not-a-real-password");
    private final String bootstrapUsername;
    private final String bootstrapDisplayName;
    private final String bootstrapPasswordFile;

    public LocalIdentityService(
            JdbcTemplate jdbc,
            AuditTrail audit,
            @Value("${td.auth.bootstrap.username:}") String bootstrapUsername,
            @Value("${td.auth.bootstrap.display-name:}") String bootstrapDisplayName,
            @Value("${td.auth.bootstrap.password-file:}") String bootstrapPasswordFile) {
        this.jdbc = jdbc;
        this.audit = audit;
        this.bootstrapUsername = bootstrapUsername;
        this.bootstrapDisplayName = bootstrapDisplayName;
        this.bootstrapPasswordFile = bootstrapPasswordFile;
    }

    @Override
    @Transactional
    public void run(ApplicationArguments arguments) throws Exception {
        int credentials = jdbc.queryForObject(
            "SELECT count(*) FROM sys_user_credential", Integer.class);
        boolean anyBootstrap = !bootstrapUsername.isBlank()
            || !bootstrapDisplayName.isBlank() || !bootstrapPasswordFile.isBlank();
        if (credentials > 0) {
            if (anyBootstrap) {
                throw new IllegalStateException(
                    "本地管理员已存在，必须移除一次性引导机密");
            }
            return;
        }
        if (!anyBootstrap) {
            return;
        }
        if (bootstrapUsername.isBlank() || bootstrapDisplayName.isBlank()
                || bootstrapPasswordFile.isBlank()) {
            throw new IllegalStateException("本地管理员引导配置不完整");
        }
        String password = Files.readString(
            Path.of(bootstrapPasswordFile), StandardCharsets.UTF_8);
        if (password.endsWith("\n")) {
            password = password.substring(0, password.length() - 1);
        }
        UUID userId = createUser(
            bootstrapUsername,
            bootstrapDisplayName,
            password,
            List.of("ADMINISTRATOR"),
            "SYSTEM_BOOTSTRAP");
        audit("SYSTEM", "bootstrap", "AUTH_BOOTSTRAP_CREATED", userId.toString(), "SUCCESS");
    }

    public String normalizeUsername(String value) {
        String normalized = value == null ? "" : value.toLowerCase(Locale.ROOT);
        if (!USERNAME.matcher(normalized).matches()) {
            throw new IllegalArgumentException("用户名格式不合法");
        }
        return normalized;
    }

    public void validatePassword(String username, String password) {
        if (password == null || password.length() < 12 || password.length() > 128
                || password.equalsIgnoreCase(username)) {
            throw new IllegalArgumentException("密码不符合安全要求");
        }
    }

    public LocalIdentity authenticate(
            String username,
            String password,
            String sourceAddress) {
        String normalized;
        try {
            normalized = normalizeUsername(username);
        } catch (IllegalArgumentException invalid) {
            passwords.matches(password == null ? "" : password, dummyHash);
            throw new BadCredentialsException("身份认证失败");
        }
        String source = safeSource(sourceAddress);
        if (blocked(normalized, source)) {
            throw new BadCredentialsException("身份认证失败");
        }
        List<Map<String, Object>> rows = jdbc.queryForList(
            """
            SELECT u.user_id, u.status, c.password_hash
            FROM sys_user u
            JOIN sys_user_credential c ON c.user_id = u.user_id
            WHERE lower(u.username) = ?
            """,
            normalized
        );
        boolean valid = !rows.isEmpty()
            && "ACTIVE".equals(rows.getFirst().get("status"))
            && passwords.matches(password == null ? "" : password,
                String.valueOf(rows.getFirst().get("password_hash")));
        if (!valid) {
            if (rows.isEmpty()) {
                passwords.matches(password == null ? "" : password, dummyHash);
            }
            recordFailure(normalized, source);
            audit("USER", normalized, "AUTH_LOGIN_FAILED", normalized, "FAILED");
            throw new BadCredentialsException("身份认证失败");
        }
        clearFailures(normalized, source);
        UUID userId = UUID.fromString(String.valueOf(rows.getFirst().get("user_id")));
        audit("USER", userId.toString(), "AUTH_LOGIN_SUCCEEDED",
            userId.toString(), "SUCCESS");
        return loadIdentity(userId);
    }

    @Transactional
    public SessionCredential createSession(
            LocalIdentity identity,
            String sourceAddress,
            String userAgent) {
        String raw = randomToken();
        Instant now = Instant.now();
        jdbc.update(
            """
            INSERT INTO auth_session(
                session_hash, user_id, created_at, last_accessed_at,
                idle_expires_at, absolute_expires_at, source_address,
                user_agent_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sha256(raw), identity.userId(), Timestamp.from(now),
            Timestamp.from(now), Timestamp.from(now.plus(IDLE)),
            Timestamp.from(now.plus(ABSOLUTE)), safeSource(sourceAddress),
            sha256(userAgent == null ? "" : userAgent)
        );
        return new SessionCredential(raw, now.plus(IDLE), now.plus(ABSOLUTE));
    }

    @Transactional
    public LocalIdentity resolveSession(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        List<Map<String, Object>> rows = jdbc.queryForList(
            """
            SELECT user_id, idle_expires_at, absolute_expires_at
            FROM auth_session
            WHERE session_hash = ? AND revoked_at IS NULL
            """,
            sha256(raw)
        );
        if (rows.isEmpty()) {
            return null;
        }
        Map<String, Object> row = rows.getFirst();
        Instant now = Instant.now();
        Instant idleExpiry = instant(row.get("idle_expires_at"));
        Instant absoluteExpiry = instant(row.get("absolute_expires_at"));
        UUID userId = UUID.fromString(String.valueOf(row.get("user_id")));
        if (!now.isBefore(idleExpiry) || !now.isBefore(absoluteExpiry)) {
            revoke(raw);
            return null;
        }
        LocalIdentity identity = loadIdentity(userId);
        if (!"ACTIVE".equals(identity.status())) {
            revoke(raw);
            return null;
        }
        Instant nextIdle = now.plus(IDLE);
        if (nextIdle.isAfter(absoluteExpiry)) {
            nextIdle = absoluteExpiry;
        }
        jdbc.update(
            """
            UPDATE auth_session SET last_accessed_at = ?, idle_expires_at = ?
            WHERE session_hash = ? AND revoked_at IS NULL
            """,
            Timestamp.from(now), Timestamp.from(nextIdle), sha256(raw)
        );
        return identity;
    }

    @Transactional
    public void revoke(String raw) {
        if (raw != null && !raw.isBlank()) {
            jdbc.update(
                "UPDATE auth_session SET revoked_at = now() "
                    + "WHERE session_hash = ? AND revoked_at IS NULL",
                sha256(raw)
            );
        }
    }

    @Transactional
    public void changePassword(
            UUID userId,
            String currentPassword,
            String newPassword) {
        Map<String, Object> row = jdbc.queryForMap(
            """
            SELECT u.username, c.password_hash
            FROM sys_user u JOIN sys_user_credential c ON c.user_id = u.user_id
            WHERE u.user_id = ?
            """,
            userId
        );
        if (!passwords.matches(currentPassword,
                String.valueOf(row.get("password_hash")))) {
            throw new BadCredentialsException("当前密码不正确");
        }
        String username = String.valueOf(row.get("username"));
        validatePassword(username, newPassword);
        jdbc.update(
            """
            UPDATE sys_user_credential
            SET password_hash = ?, password_changed_at = now()
            WHERE user_id = ?
            """,
            passwords.encode(newPassword), userId
        );
        jdbc.update(
            "UPDATE sys_user SET password_change_required = false, updated_at = now() "
                + "WHERE user_id = ?",
            userId
        );
        jdbc.update(
            "UPDATE auth_session SET revoked_at = now() "
                + "WHERE user_id = ? AND revoked_at IS NULL",
            userId
        );
        audit("USER", userId.toString(), "AUTH_PASSWORD_CHANGED",
            userId.toString(), "SUCCESS");
    }

    @Transactional
    public UUID createUser(
            String username,
            String displayName,
            String initialPassword,
            List<String> roles,
            String actor) {
        String normalized = normalizeUsername(username);
        validatePassword(normalized, initialPassword);
        if (displayName == null || displayName.isBlank()
                || displayName.length() > 256) {
            throw new IllegalArgumentException("显示名称不合法");
        }
        validateRoles(roles);
        UUID userId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO sys_user(
                user_id, username, display_name, status,
                password_change_required, person_role
            ) VALUES (?, ?, ?, 'ACTIVE', true, ?)
            """,
            userId, normalized, displayName, roles.getFirst()
        );
        jdbc.update(
            "INSERT INTO sys_user_credential(user_id, password_hash) VALUES (?, ?)",
            userId, passwords.encode(initialPassword)
        );
        replacePersonRole(userId, roles.getFirst());
        audit("USER", actor, "USER_CREATED", userId.toString(), "SUCCESS");
        return userId;
    }

    public List<Map<String, Object>> listUsers() {
        return jdbc.queryForList(
            """
            SELECT user_id, username, display_name, status,
                   password_change_required, created_at, updated_at
            FROM sys_user
            ORDER BY lower(coalesce(username, external_subject)), user_id
            LIMIT 200
            """
        ).stream().map(row -> {
            Map<String, Object> item = new LinkedHashMap<>(row);
            item.put("roles", jdbc.queryForList(
                """
                SELECT person_role FROM sys_user
                WHERE user_id = ? AND person_role IS NOT NULL
                """,
                String.class,
                row.get("user_id")
            ));
            return java.util.Collections.unmodifiableMap(item);
        }).toList();
    }

    @Transactional
    public void setStatus(UUID userId, String status, String actor) {
        if (!Set.of("ACTIVE", "DISABLED").contains(status)) {
            throw new IllegalArgumentException("用户状态不合法");
        }
        if ("ACTIVE".equals(status)) {
            int usable = jdbc.queryForObject(
                """
                SELECT count(*) FROM sys_user u
                JOIN sys_user_credential c ON c.user_id = u.user_id
                WHERE u.user_id = ? AND u.username IS NOT NULL
                """,
                Integer.class,
                userId
            );
            if (usable != 1) {
                throw new IllegalArgumentException("旧身份记录不能启用为本地账号");
            }
        }
        jdbc.update(
            "UPDATE sys_user SET status = ?, updated_at = now() WHERE user_id = ?",
            status, userId
        );
        if ("DISABLED".equals(status)) {
            jdbc.update(
                "UPDATE auth_session SET revoked_at = now() "
                    + "WHERE user_id = ? AND revoked_at IS NULL",
                userId
            );
        }
        audit("USER", actor, "USER_STATUS_CHANGED", userId.toString(), "SUCCESS");
    }

    @Transactional
    public void setDisplayName(UUID userId, String displayName, String actor) {
        if (displayName == null || displayName.isBlank()
                || displayName.length() > 256) {
            throw new IllegalArgumentException("显示名称不合法");
        }
        int updated = jdbc.update(
            "UPDATE sys_user SET display_name = ?, updated_at = now() "
                + "WHERE user_id = ?",
            displayName,
            userId
        );
        if (updated != 1) {
            throw new IllegalArgumentException("用户不存在：" + userId);
        }
        audit("USER", actor, "USER_DISPLAY_NAME_CHANGED", userId.toString(), "SUCCESS");
    }

    @Transactional
    public void setRoles(UUID userId, List<String> roles, String actor) {
        validateRoles(roles);
        ensureRoleMigrationRows();
        List<String> migrationStatuses = jdbc.queryForList(
            "SELECT status FROM sys_user_role_migration_v2 WHERE user_id = ?",
            String.class,
            userId
        );
        if (!migrationStatuses.isEmpty()) {
            if (!"CONFIRMED".equals(migrationStatuses.getFirst())) {
                throw new IllegalStateException("该账号必须通过角色迁移确认接口完成映射");
            }
            confirmRoleMigration(userId, roles.getFirst(), actor, "用户管理角色变更");
            return;
        }
        String currentRole = jdbc.queryForObject(
            "SELECT person_role FROM sys_user WHERE user_id = ?",
            String.class,
            userId
        );
        if (currentRole == null) {
            throw new IllegalStateException("该账号未完成角色迁移确认");
        }
        replacePersonRole(userId, roles.getFirst());
        jdbc.update(
            "UPDATE auth_session SET revoked_at = now() "
                + "WHERE user_id = ? AND revoked_at IS NULL",
            userId
        );
        audit("USER", actor, "USER_ROLE_CHANGED", userId.toString(), "SUCCESS");
    }

    /**
     * 生成旧角色影响预览；该操作只补齐当前快照，不改变用户角色或会话。
     */
    @Transactional
    public List<Map<String, Object>> previewRoleMappings() {
        ensureRoleMigrationRows();
        return jdbc.queryForList(
            """
            SELECT m.user_id, u.username, u.display_name, u.status,
                   m.legacy_roles, m.suggested_role, m.selected_role,
                   m.status AS migration_status, m.decision_reason
            FROM sys_user_role_migration_v2 m
            JOIN sys_user u ON u.user_id = m.user_id
            ORDER BY lower(coalesce(u.username, u.external_subject)), m.user_id
            """
        ).stream().map(row -> {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("user_id", row.get("user_id"));
            item.put("username", row.get("username"));
            item.put("display_name", row.get("display_name"));
            item.put("status", row.get("status"));
            item.put("legacy_roles", roleArray(row.get("legacy_roles")));
            item.put("suggested_role", row.get("suggested_role"));
            item.put("selected_role", row.get("selected_role"));
            item.put("migration_status", row.get("migration_status"));
            item.put("decision_reason", row.get("decision_reason"));
            return java.util.Collections.unmodifiableMap(item);
        }).toList();
    }

    /**
     * 逐账号确认角色映射。相同确认重复执行幂等，改变既有决定则明确冲突。
     */
    @Transactional
    public Map<String, Object> confirmRoleMigration(
            UUID userId,
            String targetRole,
            String actor,
            String reason) {
        validateRole(targetRole);
        ensureRoleMigrationRows();
        Map<String, Object> mapping = jdbc.queryForMap(
            """
            SELECT status, selected_role, legacy_roles
            FROM sys_user_role_migration_v2
            WHERE user_id = ? FOR UPDATE
            """,
            userId
        );
        String status = String.valueOf(mapping.get("status"));
        String selected = mapping.get("selected_role") == null
            ? null : String.valueOf(mapping.get("selected_role"));
        if ("CONFIRMED".equals(status)) {
            if (targetRole.equals(selected)) {
                return Map.of(
                    "user_id", userId.toString(),
                    "role", targetRole,
                    "status", "CONFIRMED",
                    "idempotent", true
                );
            }
            throw new IllegalStateException("角色映射已确认且新旧决定冲突");
        }
        List<String> legacyRoles = roleArray(mapping.get("legacy_roles"));
        boolean conflict = "CONFLICT".equals(status);
        if ((conflict && (reason == null || reason.isBlank()))
                || ("ADMINISTRATOR".equals(targetRole)
                    && (legacyRoles.stream().anyMatch(LEGACY_HIGH_PRIVILEGE_ROLES::contains)
                        && (reason == null || reason.isBlank())))) {
            throw new IllegalArgumentException("冲突或高权限角色映射必须提供明确确认原因");
        }
        replacePersonRole(userId, targetRole);
        jdbc.update(
            """
            UPDATE sys_user_role_migration_v2
            SET selected_role = ?, status = 'CONFIRMED', decision_reason = ?,
                decided_by = ?, decided_at = now(), updated_at = now(),
                record_version = record_version + 1
            WHERE user_id = ?
            """,
            targetRole, reason, actorUuid(actor), userId
        );
        jdbc.update(
            "UPDATE auth_session SET revoked_at = now() "
                + "WHERE user_id = ? AND revoked_at IS NULL",
            userId
        );
        audit("USER", actor, "USER_ROLE_MIGRATION_CONFIRMED",
            userId.toString(), "SUCCESS");
        return Map.of(
            "user_id", userId.toString(),
            "role", targetRole,
            "status", "CONFIRMED",
            "idempotent", false
        );
    }

    @Transactional
    public void resetPassword(
            UUID userId,
            String temporaryPassword,
            String actor) {
        String username = jdbc.queryForObject(
            "SELECT username FROM sys_user WHERE user_id = ?",
            String.class,
            userId
        );
        validatePassword(username, temporaryPassword);
        jdbc.update(
            """
            UPDATE sys_user_credential
            SET password_hash = ?, password_changed_at = now()
            WHERE user_id = ?
            """,
            passwords.encode(temporaryPassword), userId
        );
        jdbc.update(
            "UPDATE sys_user SET password_change_required = true, updated_at = now() "
                + "WHERE user_id = ?",
            userId
        );
        jdbc.update(
            "UPDATE auth_session SET revoked_at = now() "
                + "WHERE user_id = ? AND revoked_at IS NULL",
            userId
        );
        audit("USER", actor, "USER_PASSWORD_RESET", userId.toString(), "SUCCESS");
    }

    public LocalIdentity loadIdentity(UUID userId) {
        Map<String, Object> user = jdbc.queryForMap(
            """
            SELECT user_id, username, display_name, status,
                   password_change_required, person_role
            FROM sys_user WHERE user_id = ?
            """,
            userId
        );
        String personRole = (String) user.get("person_role");
        List<String> roles = personRole == null ? List.of() : List.of(personRole);
        List<String> permissions = jdbc.queryForList(
            """
            SELECT DISTINCT p.permission_code FROM sys_permission p
            JOIN sys_role_permission rp ON rp.permission_id = p.permission_id
            JOIN sys_role r ON r.role_id = rp.role_id
            JOIN sys_user u ON u.person_role = r.role_code
            WHERE u.user_id = ? ORDER BY p.permission_code
            """,
            String.class,
            userId
        );
        return new LocalIdentity(
            userId,
            String.valueOf(user.get("username")),
            String.valueOf(user.get("display_name")),
            String.valueOf(user.get("status")),
            Boolean.TRUE.equals(user.get("password_change_required")),
            List.copyOf(roles),
            List.copyOf(permissions)
        );
    }

    private void replacePersonRole(UUID userId, String role) {
        validateRole(role);
        int updated = jdbc.update(
            "UPDATE sys_user SET person_role = ?, updated_at = now() WHERE user_id = ?",
            role, userId
        );
        if (updated != 1) {
            throw new IllegalArgumentException("用户不存在：" + userId);
        }
        jdbc.update(
            """
            DELETE FROM sys_user_role
            WHERE user_id = ? AND role_id IN (
                SELECT role_id FROM sys_role
                WHERE role_code IN ('PRODUCTION_EMPLOYEE', 'ADMINISTRATOR')
            )
            """,
            userId
        );
        int inserted = jdbc.update(
            """
            INSERT INTO sys_user_role(user_id, role_id)
            SELECT ?, role_id FROM sys_role WHERE role_code = ?
            """,
            userId, role
        );
        if (inserted != 1) {
            throw new IllegalArgumentException("第二版角色不存在：" + role);
        }
    }

    private void validateRoles(List<String> roles) {
        if (roles == null || roles.size() != 1) {
            throw new IllegalArgumentException("第二版账号必须且只能分配一个人员角色");
        }
        validateRole(roles.getFirst());
    }

    private void validateRole(String role) {
        if (role == null || !PERSON_ROLES.contains(role)) {
            throw new IllegalArgumentException("第二版人员角色不合法");
        }
    }

    private void ensureRoleMigrationRows() {
        jdbc.update(
            """
            INSERT INTO sys_user_role_migration_v2(
                migration_id, user_id, legacy_roles, suggested_role, status
            )
            SELECT gen_random_uuid(), u.user_id,
                   COALESCE(
                       array_agg(r.role_code ORDER BY r.role_code)
                           FILTER (WHERE r.role_code IS NOT NULL),
                       ARRAY[]::varchar(64)[]
                   ),
                   CASE
                       WHEN count(r.role_code) = 1
                            AND min(r.role_code) = 'OPERATOR'
                           THEN 'PRODUCTION_EMPLOYEE'
                       ELSE NULL
                   END,
                   CASE
                       WHEN count(r.role_code) = 0
                           THEN 'UNCONFIRMED'
                       WHEN count(r.role_code) = 1
                            AND min(r.role_code) = 'OPERATOR'
                           THEN 'UNCONFIRMED'
                       ELSE 'CONFLICT'
                   END
            FROM sys_user u
            LEFT JOIN sys_user_role ur ON ur.user_id = u.user_id
            LEFT JOIN sys_role r ON r.role_id = ur.role_id
            WHERE u.person_role IS NULL
            GROUP BY u.user_id
            ON CONFLICT (user_id) DO NOTHING
            """);
    }

    private static List<String> roleArray(Object value) {
        if (value == null) {
            return List.of();
        }
        if (value instanceof String[] roles) {
            return List.of(roles);
        }
        if (value instanceof java.sql.Array sqlArray) {
            try {
                Object array = sqlArray.getArray();
                if (array instanceof String[] roles) {
                    return List.of(roles);
                }
            } catch (java.sql.SQLException exception) {
                throw new IllegalStateException("读取旧角色快照失败", exception);
            }
        }
        return List.of(String.valueOf(value));
    }

    private static UUID actorUuid(String actor) {
        try {
            return UUID.fromString(actor);
        } catch (RuntimeException notUuid) {
            return null;
        }
    }

    private boolean blocked(String username, String source) {
        List<Instant> values = jdbc.query(
            """
            SELECT blocked_until FROM auth_login_failure
            WHERE normalized_username = ? AND source_address = ?
              AND blocked_until > now()
            """,
            (result, row) -> result.getTimestamp(1).toInstant(),
            username, source
        );
        return !values.isEmpty();
    }

    private void recordFailure(String username, String source) {
        jdbc.update(
            """
            INSERT INTO auth_login_failure(
                normalized_username, source_address, window_started_at,
                failure_count, blocked_until
            ) VALUES (?, ?, now(), 1, NULL)
            ON CONFLICT (normalized_username, source_address) DO UPDATE SET
                failure_count = CASE
                    WHEN auth_login_failure.window_started_at < now() - interval '15 minutes'
                    THEN 1 ELSE auth_login_failure.failure_count + 1 END,
                window_started_at = CASE
                    WHEN auth_login_failure.window_started_at < now() - interval '15 minutes'
                    THEN now() ELSE auth_login_failure.window_started_at END,
                blocked_until = CASE
                    WHEN auth_login_failure.window_started_at >= now() - interval '15 minutes'
                     AND auth_login_failure.failure_count + 1 >= 5
                    THEN now() + interval '15 minutes' ELSE NULL END
            """,
            username, source
        );
    }

    private void clearFailures(String username, String source) {
        jdbc.update(
            "DELETE FROM auth_login_failure "
                + "WHERE normalized_username = ? AND source_address = ?",
            username, source
        );
    }

    private void audit(
            String actorType,
            String actorId,
            String action,
            String resourceId,
            String result) {
        String requestId = UUID.randomUUID().toString();
        audit.append(new AuditRecord(
            UUID.randomUUID(), Instant.now(), actorType, actorId, action,
            "IDENTITY", resourceId, null, null, null, requestId,
            requestId.replace("-", ""), result,
            "FAILED".equals(result) ? "TD-AUTH-UNAUTHORIZED-001" : null
        ));
    }

    private static String safeSource(String value) {
        if (value == null || value.isBlank()) {
            return "unknown";
        }
        return value.substring(0, Math.min(value.length(), 128));
    }

    private static Instant instant(Object value) {
        if (value instanceof Instant instant) {
            return instant;
        }
        if (value instanceof java.time.OffsetDateTime offset) {
            return offset.toInstant();
        }
        if (value instanceof java.sql.Timestamp timestamp) {
            return timestamp.toInstant();
        }
        throw new IllegalStateException("数据库时间字段类型不受支持");
    }

    private static String randomToken() {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    public static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(
                MessageDigest.getInstance("SHA-256").digest(
                    value.getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    public record SessionCredential(
            String token,
            Instant idleExpiresAt,
            Instant absoluteExpiresAt) {
    }
}
