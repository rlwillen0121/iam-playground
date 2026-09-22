"""REST profile names. These applications are not SCIM app-a or app-b."""

APP_MODERN = "rest-modern"
APP_LEGACY = "rest-legacy"
APPLICATIONS = (APP_MODERN, APP_LEGACY)

CLIENT_MODERN = "rest-modern"
CLIENT_MODERN_READ = "rest-modern-read"
CLIENT_LEGACY = "rest-legacy"
CLIENT_LEGACY_READ = "rest-legacy-read"

# Listed in API order. rest.sql seeds the same names.
ROLES = ("admin", "operator", "reader")

PAGE_DEFAULT = 50
PAGE_MAX = 100
PAGE_NUMBER_MAX = 10000
ACCOUNT_ID_MAX = 2147483647
BODY_MAX_BYTES = 65536
TEXT_MAX = 200
IDEMPOTENCY_KEY_MAX = 255

KIND_CREATE = "create-account"
KIND_PATCH = "patch-account"
KIND_DELETE = "delete-account"
KIND_ENABLE = "enable-account"
KIND_DISABLE = "disable-account"
KIND_ASSIGN = "assign-role"
KIND_REMOVE = "remove-role"

KINDS = (
    KIND_CREATE,
    KIND_PATCH,
    KIND_DELETE,
    KIND_ENABLE,
    KIND_DISABLE,
    KIND_ASSIGN,
    KIND_REMOVE,
)

OP_LIST_ACCOUNTS = "list-accounts"
OP_GET_ACCOUNT = "get-account"
OP_LIST_ROLES = "list-roles"
OP_GET_OPERATION = "get-operation"
OP_CANCEL = "cancel-operation"

OPERATIONS = KINDS + (
    OP_LIST_ACCOUNTS,
    OP_GET_ACCOUNT,
    OP_LIST_ROLES,
    OP_GET_OPERATION,
    OP_CANCEL,
)

STATE_ACCEPTED = "accepted"
STATE_RUNNING = "running"
STATE_SUCCEEDED = "succeeded"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"
STATES = (
    STATE_ACCEPTED,
    STATE_RUNNING,
    STATE_SUCCEEDED,
    STATE_FAILED,
    STATE_CANCELLED,
)
TERMINAL_STATES = (STATE_SUCCEEDED, STATE_FAILED, STATE_CANCELLED)

STATUS_ENABLED = "enabled"
STATUS_DISABLED = "disabled"
STATUSES = (STATUS_ENABLED, STATUS_DISABLED)

FAULT_429 = "429"
FAULT_503 = "503"
FAULT_STALE_READ = "stale-read"
FAULT_ASYNC_FAILURE = "async-failure"
FAULT_MALFORMED_LIST = "malformed-list"
FAULT_COMMIT_TIMEOUT = "commit-timeout"
FAULTS = (
    FAULT_429,
    FAULT_503,
    FAULT_STALE_READ,
    FAULT_ASYNC_FAILURE,
    FAULT_MALFORMED_LIST,
    FAULT_COMMIT_TIMEOUT,
)
TRANSPORT_FAULTS = frozenset({FAULT_429, FAULT_503})
OUTCOME_FAULTS = frozenset({FAULT_ASYNC_FAILURE, FAULT_COMMIT_TIMEOUT})

FAULT_HEADER = "X-Lab-Fault"
RETRY_AFTER_SECONDS = "1"

STALE_GENERATION = "stale generation"
ASYNC_FAILURE_ERROR = "async-failure"
IDEMPOTENCY_CONFLICT = "idempotency key was reused with a different payload"
LOGIN_CONFLICT = "login is already in use"
NOT_ACCEPTING = "lab is not accepting"
SUCCEEDED_NOT_ROLLED_BACK = "succeeded operation was not rolled back"
ALREADY_FINISHED = "operation is already finished"
