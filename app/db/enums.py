from enum import StrEnum


class EmployeeRole(StrEnum):
    EMPLOYEE = "employee"
    HR = "hr"
    ADMIN = "admin"


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
