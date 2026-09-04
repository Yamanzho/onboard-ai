from enum import StrEnum


class EmployeeRole(StrEnum):
    """Company-scoped employee roles. Unchanged for tenant multi-tenancy."""

    EMPLOYEE = "employee"
    HR = "hr"
    ADMIN = "admin"


class InvitePurpose(StrEnum):
    """Server-side invitation / reset purpose, snapshotted on the invite row.

    Onboarding values (employee/hr/admin) mirror EmployeeRole. Accept flows must
    derive role/company from the invite row (token lookup), never from client
    input. ``password_reset`` is a separate lifecycle for ACTIVE employees and
    must never be treated as a role assignment.
    """

    EMPLOYEE = "employee"
    HR = "hr"
    ADMIN = "admin"
    PASSWORD_RESET = "password_reset"


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


class AssignmentPriority(StrEnum):
    NORMAL = "normal"
    IMPORTANT = "important"
    CRITICAL = "critical"


class ProgressStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class AIMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


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


class KnowledgeIndexStatus(StrEnum):
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


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
    USER_RESTORED = "user.restored"
    USER_INVITED = "user.invited"
    SETTINGS_UPDATED = "settings.updated"


class CompanyAuditAction(StrEnum):
    """Tenant-scoped HR/Admin actions. Never store tokens or passwords in details."""

    EMPLOYEE_CREATED = "employee.created"
    EMPLOYEE_UPDATED = "employee.updated"
    EMPLOYEE_ARCHIVED = "employee.archived"
    INVITE_CREATED = "invite.created"
    INVITE_RESENT = "invite.resent"
    INVITE_ACCEPTED = "invite.accepted"
    PROGRAM_CREATED = "program.created"
    PROGRAM_PUBLISHED = "program.published"
    PROGRAM_ARCHIVED = "program.archived"
    ASSIGNMENT_CREATED = "assignment.created"
    ASSIGNMENT_CHANGED = "assignment.changed"
    ARTICLE_CREATED = "kb.article.created"
    ARTICLE_UPDATED = "kb.article.updated"
    ARTICLE_PUBLISHED = "kb.article.published"
    ARTICLE_ARCHIVED = "kb.article.archived"
    DEPARTMENT_CREATED = "department.created"
    DEPARTMENT_UPDATED = "department.updated"
    TOPIC_CREATED = "topic.created"
    TOPIC_UPDATED = "topic.updated"
    TOPIC_RESPONSIBILITY_CHANGED = "topic.responsibility.changed"
