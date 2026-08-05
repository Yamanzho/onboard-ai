from enum import StrEnum


class EmployeeRole(StrEnum):
    """Company-scoped employee roles. Unchanged for tenant multi-tenancy."""

    EMPLOYEE = "employee"
    HR = "hr"
    ADMIN = "admin"


class PlatformRole(StrEnum):
    """Platform-level roles (not tied to any company)."""

    SUPER_ADMIN = "super_admin"


class EmployeeStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    ARCHIVED = "archived"


class StepType(StrEnum):
    CONTENT = "content"
    TASK = "task"
    QUIZ = "quiz"
    ACK = "ack"


class AssignmentStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProgressStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class KnowledgeArticleStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class KnowledgeVisibility(StrEnum):
    COMPANY = "company"
    PROGRAM = "program"


class KnowledgeBodyFormat(StrEnum):
    MARKDOWN = "markdown"
    HTML = "html"
    PLAIN = "plain"


class KnowledgeLinkTargetType(StrEnum):
    PROGRAM = "program"
    STEP = "step"


class SubscriptionTier(StrEnum):
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    BLOCKED = "blocked"


class PaymentStatus(StrEnum):
    UNPAID = "unpaid"
    PAID = "paid"
    PAST_DUE = "past_due"


class SubscriptionHistoryEventType(StrEnum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    TIER_CHANGED = "tier_changed"
    RENEWED = "renewed"
    AUTO_RENEW_CHANGED = "auto_renew_changed"


class PlatformAuditAction(StrEnum):
    COMPANY_CREATED = "company.created"
    COMPANY_UPDATED = "company.updated"
    COMPANY_ACTIVATED = "company.activated"
    COMPANY_DEACTIVATED = "company.deactivated"
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_UPDATED = "subscription.updated"
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_BLOCKED = "user.blocked"
    USER_INVITED = "user.invited"
    SETTINGS_UPDATED = "settings.updated"
