import enum


class Channel(str, enum.Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    IN_APP = "in_app"


class UserRole(str, enum.Enum):
    PLATFORM_ADMIN = "platform_admin"
    TENANT_ADMIN = "tenant_admin"


class NotificationStatus(str, enum.Enum):
    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIALLY_FAILED = "PARTIALLY_FAILED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DeliveryStatus(str, enum.Enum):
    # Matches the CLAUDE.md state machine exactly:
    # CREATED → SCHEDULED → PENDING → SENDING → SENT | FAILED → RETRYING → DEAD_LETTERED
    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    DEAD_LETTERED = "DEAD_LETTERED"
