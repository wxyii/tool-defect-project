# Copy this file to .windows.env.ps1 and fill every required value.
# The copied file is ignored by Git. Do not commit passwords, tokens, or keys.
# On the first Windows start, an empty local account table triggers an interactive
# administrator setup. Do not add TD_BOOTSTRAP_ADMIN_* values to this file.

$env:TD_DATABASE_URL = "jdbc:postgresql://127.0.0.1:5432/tool_defect"
$env:TD_DATABASE_USERNAME = ""
$env:TD_DATABASE_PASSWORD = ""

$env:TD_RABBITMQ_ADDRESSES = "127.0.0.1:5672"
$env:TD_RABBITMQ_USERNAME = ""
$env:TD_RABBITMQ_PASSWORD = ""
$env:TD_RABBITMQ_SSL_ENABLED = "false"

$env:TD_S3_ENDPOINT = "http://127.0.0.1:9000"
$env:TD_S3_ACCESS_KEY = ""
$env:TD_S3_SECRET_KEY = ""
$env:TD_S3_REQUIRE_TLS = "false"
$env:TD_S3_PATH_STYLE = "true"

# The native start action intentionally requires the full development stack.
$env:TD_MESSAGING_ENABLED = "true"
$env:TD_STORAGE_ENABLED = "true"
$env:TD_OPERATIONS_ENABLED = "true"
$env:TD_AUTH_SECURE_COOKIE = "false"
$env:TD_MANAGEMENT_PORT = "9091"
$env:TD_ENVIRONMENT = "development"
$env:TD_SERVICE_VERSION = "workspace"

# Required Windows service names. Names are installation-specific and have no defaults.
$env:TD_WINDOWS_POSTGRES_SERVICE = ""
$env:TD_WINDOWS_RABBITMQ_SERVICE = ""
$env:TD_WINDOWS_OBJECT_STORAGE_SERVICE = ""
$env:TD_WINDOWS_OTEL_SERVICE = ""
$env:TD_WINDOWS_PROMETHEUS_SERVICE = ""
$env:TD_WINDOWS_GRAFANA_SERVICE = ""
$env:TD_WINDOWS_LOKI_SERVICE = ""
$env:TD_WINDOWS_TEMPO_SERVICE = ""
