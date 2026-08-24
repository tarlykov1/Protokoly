from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IntegrationSettings(TimestampMixin, Base):
    """Administrator-managed configuration for an external integration."""

    __tablename__ = "integration_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(64), unique=True, default="bitrix24")
    enabled: Mapped[bool] = mapped_column(Boolean(), default=True)
    mode: Mapped[str] = mapped_column(String(16), default="fake")
    portal_url: Mapped[str | None] = mapped_column(String(1000))
    webhook_url: Mapped[str | None] = mapped_column(String(1000))
    user_id: Mapped[str | None] = mapped_column(String(64))
    encrypted_token: Mapped[str | None] = mapped_column(Text())


class IntegrationLog(Base):
    """Audit trail of calls made to an integration (secrets are redacted by the gateway)."""

    __tablename__ = "integration_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    operation: Mapped[str] = mapped_column(String(128), index=True)
    request: Mapped[dict | None] = mapped_column(JSON())
    response: Mapped[dict | None] = mapped_column(JSON())
    status: Mapped[str] = mapped_column(String(32))
    request_id: Mapped[str | None] = mapped_column(String(128), index=True)
    attempts: Mapped[int] = mapped_column(Integer(), default=1)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmployeeSourceSettings(TimestampMixin, Base):
    """Configuration of the employee directory's active provider."""

    __tablename__ = "employee_source_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_type: Mapped[str] = mapped_column(String(32), default="manual")
    enabled: Mapped[bool] = mapped_column(Boolean(), default=True)
    parameters: Mapped[dict] = mapped_column(JSON(), default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(32))
    last_sync_message: Mapped[str | None] = mapped_column(Text())


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str | None] = mapped_column(Text())
    bitrix_group_id: Mapped[int | None] = mapped_column(Integer())
    technical_user_id: Mapped[int | None] = mapped_column(Integer())
    numbering_prefix: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True)
    directions: Mapped[list["Direction"]] = relationship(back_populates="project")
    protocols: Mapped[list["Protocol"]] = relationship(back_populates="project")


class Direction(Base):
    __tablename__ = "directions"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True)
    sort_order: Mapped[int] = mapped_column(Integer(), default=0)
    project: Mapped[Project] = relationship(back_populates="directions")


class Block(Base):
    __tablename__ = "blocks"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    direction_id: Mapped[int] = mapped_column(ForeignKey("directions.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True)
    sort_order: Mapped[int] = mapped_column(Integer(), default=0)


class Employee(TimestampMixin, Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    position: Mapped[str | None] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(100))
    first_name: Mapped[str | None] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    personnel_number: Mapped[str | None] = mapped_column(String(64), unique=True)
    bitrix_user_id: Mapped[int | None] = mapped_column(Integer())
    source_system: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True)
    is_available_in_bitrix: Mapped[bool] = mapped_column(Boolean(), default=False)


class EmployeeAlias(Base):
    __tablename__ = "employee_aliases"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(String(255))
    normalized_alias: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmployeeList(TimestampMixin, Base):
    __tablename__ = "employee_lists"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text())
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True)
    members: Mapped[list["EmployeeListMember"]] = relationship(back_populates="employee_list")


class EmployeeListMember(Base):
    __tablename__ = "employee_list_members"
    __table_args__ = (UniqueConstraint("employee_list_id", "employee_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_list_id: Mapped[int] = mapped_column(
        ForeignKey("employee_lists.id", ondelete="CASCADE")
    )
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    sort_order: Mapped[int] = mapped_column(Integer(), default=0)
    employee_list: Mapped[EmployeeList] = relationship(back_populates="members")
    employee: Mapped[Employee] = relationship()


class Protocol(TimestampMixin, Base):
    __tablename__ = "protocols"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer(), default=1, nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    protocol_type: Mapped[str] = mapped_column(String(64), default="protocol")
    title: Mapped[str] = mapped_column(String(500))
    number: Mapped[str | None] = mapped_column(String(64))
    meeting_date: Mapped[date | None] = mapped_column(Date())
    location: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    source_type: Mapped[str] = mapped_column(String(32), default="manual")
    source_filename: Mapped[str | None] = mapped_column(String(255))
    source_file_path: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str | None] = mapped_column(String(255))
    initiator: Mapped[str | None] = mapped_column(String(255))
    responsible: Mapped[str | None] = mapped_column(String(255))
    participants: Mapped[str | None] = mapped_column(Text())
    description: Mapped[str | None] = mapped_column(Text())
    project: Mapped[Project] = relationship(back_populates="protocols")
    tasks: Mapped[list["ProtocolTask"]] = relationship(back_populates="protocol")
    participant_groups: Mapped[list["ProtocolParticipantGroup"]] = relationship(
        back_populates="protocol", cascade="all, delete-orphan"
    )
    publication_settings: Mapped["PublicationSettings | None"] = relationship(
        back_populates="protocol", cascade="all, delete-orphan", uselist=False
    )
    history: Mapped[list["ProtocolHistory"]] = relationship(
        back_populates="protocol", cascade="all, delete-orphan", order_by="ProtocolHistory.created_at.desc()"
    )
    document_versions: Mapped[list["ProtocolDocumentVersion"]] = relationship(
        back_populates="protocol", cascade="all, delete-orphan", order_by="ProtocolDocumentVersion.version.desc()"
    )
    publication_runs: Mapped[list["PublicationRun"]] = relationship(
        back_populates="protocol", cascade="all, delete-orphan", order_by="PublicationRun.id"
    )


class ProtocolHistory(Base):
    """Immutable, user-facing audit event for a protocol aggregate."""

    __tablename__ = "protocol_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocols.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    user: Mapped[str] = mapped_column(String(255))
    details: Mapped[dict] = mapped_column(JSON(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    protocol: Mapped[Protocol] = relationship(back_populates="history")


class ProtocolDocumentVersion(Base):
    """Registry entry for an exported DOCX; files may live in external storage."""

    __tablename__ = "protocol_document_versions"
    __table_args__ = (UniqueConstraint("protocol_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocols.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer())
    user: Mapped[str] = mapped_column(String(255))
    file_url: Mapped[str] = mapped_column(String(1000))
    exported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    protocol: Mapped[Protocol] = relationship(back_populates="document_versions")


class PublicationSettings(TimestampMixin, Base):
    """Protocol-specific, durable Bitrix24 publication choices."""

    __tablename__ = "publication_settings"
    __table_args__ = (UniqueConstraint("protocol_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_id: Mapped[int] = mapped_column(
        ForeignKey("protocols.id", ondelete="CASCADE"), index=True
    )
    bitrix_project_id: Mapped[int | None] = mapped_column(Integer())
    task_creator_id: Mapped[int | None] = mapped_column(Integer())
    default_responsible_id: Mapped[int | None] = mapped_column(Integer())
    parent_task_mode: Mapped[str] = mapped_column(String(32), default="separate")
    root_task_title: Mapped[str | None] = mapped_column(String(500))
    observers: Mapped[list] = mapped_column(JSON(), default=list)
    accomplices: Mapped[list] = mapped_column(JSON(), default=list)
    create_checklist: Mapped[bool] = mapped_column(Boolean(), default=False)
    add_protocol_link: Mapped[bool] = mapped_column(Boolean(), default=True)
    sync_enabled: Mapped[bool] = mapped_column(Boolean(), default=True)
    custom_fields: Mapped[dict] = mapped_column(JSON(), default=dict)
    protocol: Mapped[Protocol] = relationship(back_populates="publication_settings")


class ProtocolParticipantGroup(TimestampMixin, Base):
    """A protocol-local, independently editable list of participants."""

    __tablename__ = "protocol_participant_groups"
    __table_args__ = (UniqueConstraint("protocol_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocols.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(32), default="custom")
    protocol: Mapped[Protocol] = relationship(back_populates="participant_groups")
    members: Mapped[list["ProtocolParticipantGroupMember"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="ProtocolParticipantGroupMember.id",
    )


class ProtocolParticipantGroupMember(Base):
    __tablename__ = "protocol_participant_group_members"
    __table_args__ = (UniqueConstraint("group_id", "employee_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("protocol_participant_groups.id", ondelete="CASCADE")
    )
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    name_snapshot: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32), default="manual")
    group: Mapped[ProtocolParticipantGroup] = relationship(back_populates="members")
    employee: Mapped[Employee] = relationship()


class ParticipantGroupTemplate(TimestampMixin, Base):
    """Globally reusable template; copying it never links protocol membership back to it."""

    __tablename__ = "participant_group_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    members: Mapped[list["ParticipantGroupTemplateMember"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class ParticipantGroupTemplateMember(Base):
    __tablename__ = "participant_group_template_members"
    __table_args__ = (UniqueConstraint("template_id", "employee_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("participant_group_templates.id", ondelete="CASCADE")
    )
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    name_snapshot: Mapped[str] = mapped_column(String(255))
    template: Mapped[ParticipantGroupTemplate] = relationship(back_populates="members")
    employee: Mapped[Employee] = relationship()


class ProtocolSection(Base):
    __tablename__ = "protocol_sections"
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocols.id", ondelete="CASCADE"))
    direction_id: Mapped[int | None] = mapped_column(ForeignKey("directions.id"))
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"))
    title: Mapped[str] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(Integer(), default=0)
    source_page: Mapped[int | None] = mapped_column(Integer())
    source_paragraph: Mapped[int | None] = mapped_column(Integer())
    source_table: Mapped[int | None] = mapped_column(Integer())
    original_text: Mapped[str | None] = mapped_column(Text())


class ProtocolTask(TimestampMixin, Base):
    __tablename__ = "protocol_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer(), default=1, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocols.id", ondelete="CASCADE"))
    section_id: Mapped[int | None] = mapped_column(ForeignKey("protocol_sections.id"))
    parent_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("protocol_tasks.id", ondelete="SET NULL")
    )
    number: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer(), default=0)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text())
    acceptance_criteria: Mapped[str | None] = mapped_column(Text())
    deadline: Mapped[date | None] = mapped_column(Date())
    original_deadline: Mapped[date | None] = mapped_column(Date())
    include_in_report: Mapped[bool] = mapped_column(Boolean(), default=True)
    priority: Mapped[str | None] = mapped_column(String(32))
    create_as_subtasks: Mapped[bool] = mapped_column(Boolean(), default=False)
    is_controlled: Mapped[bool] = mapped_column(Boolean(), default=False)
    status: Mapped[str] = mapped_column(String(32), default="new")
    validation_status: Mapped[str] = mapped_column(String(32), default="draft")
    original_text: Mapped[str | None] = mapped_column(Text())
    source_page: Mapped[int | None] = mapped_column(Integer())
    source_paragraph: Mapped[int | None] = mapped_column(Integer())
    source_table: Mapped[int | None] = mapped_column(Integer())
    protocol: Mapped[Protocol] = relationship(back_populates="tasks")
    assignments: Mapped[list["ProtocolTaskAssignment"]] = relationship(
        back_populates="protocol_task", cascade="all, delete-orphan"
    )
    participant_group_selections: Mapped[list["ProtocolTaskParticipantGroup"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="ProtocolTaskParticipantGroup.sort_order",
    )
    bitrix_links: Mapped[list["BitrixTaskLink"]] = relationship(back_populates="protocol_task")
    external_links: Mapped[list["ProtocolTaskLink"]] = relationship(
        back_populates="protocol_task", cascade="all, delete-orphan"
    )
    status_history: Mapped[list["ProtocolTaskStatusHistory"]] = relationship(
        back_populates="protocol_task", cascade="all, delete-orphan"
    )
    control: Mapped["ProtocolTaskControl | None"] = relationship(
        back_populates="protocol_task", cascade="all, delete-orphan", uselist=False
    )


class ProtocolTaskControl(TimestampMixin, Base):
    """Current execution state of a published protocol instruction."""

    __tablename__ = "protocol_task_controls"
    __table_args__ = (UniqueConstraint("protocol_task_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_task_id: Mapped[int] = mapped_column(
        ForeignKey("protocol_tasks.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="pending")
    planned_date: Mapped[date | None] = mapped_column(Date())
    actual_date: Mapped[date | None] = mapped_column(Date())
    result_comment: Mapped[str | None] = mapped_column(Text())
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    protocol_task: Mapped[ProtocolTask] = relationship(back_populates="control")


class ProtocolTaskStatusHistory(Base):
    __tablename__ = "protocol_task_status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_task_id: Mapped[int] = mapped_column(
        ForeignKey("protocol_tasks.id", ondelete="CASCADE"), index=True
    )
    old_status: Mapped[str] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(Text())
    changed_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    protocol_task: Mapped[ProtocolTask] = relationship(back_populates="status_history")


class ProtocolTaskAssignment(Base):
    __tablename__ = "protocol_task_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_task_id: Mapped[int] = mapped_column(
        ForeignKey("protocol_tasks.id", ondelete="CASCADE")
    )
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    source_employee_list_id: Mapped[int | None] = mapped_column(ForeignKey("employee_lists.id"))
    source_participant_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("protocol_participant_groups.id", ondelete="SET NULL")
    )
    individual_title: Mapped[str | None] = mapped_column(String(500))
    individual_description: Mapped[str | None] = mapped_column(Text())
    individual_acceptance_criteria: Mapped[str | None] = mapped_column(Text())
    individual_deadline: Mapped[date | None] = mapped_column(Date())
    individual_priority: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer(), default=0)
    protocol_task: Mapped[ProtocolTask] = relationship(back_populates="assignments")
    employee: Mapped[Employee | None] = relationship()

    @property
    def assignee_name(self) -> str | None:
        """Name shown for both resolved employees and assignees preserved from an import."""
        return self.employee.full_name if self.employee else self.individual_title

    @property
    def name_snapshot(self) -> str | None:
        """Stable imported display name; unresolved imports intentionally have no employee."""
        return self.individual_title


class ProtocolTaskParticipantGroup(Base):
    """A durable group selection; members are resolved only when a plan is built."""

    __tablename__ = "protocol_task_participant_groups"
    __table_args__ = (UniqueConstraint("protocol_task_id", "participant_group_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_task_id: Mapped[int] = mapped_column(
        ForeignKey("protocol_tasks.id", ondelete="CASCADE"), index=True
    )
    participant_group_id: Mapped[int] = mapped_column(
        ForeignKey("protocol_participant_groups.id", ondelete="CASCADE"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer(), default=0)
    group: Mapped[ProtocolParticipantGroup] = relationship()
    task: Mapped[ProtocolTask] = relationship(back_populates="participant_group_selections")


class BitrixTaskLink(Base):
    __tablename__ = "bitrix_task_links"
    __table_args__ = (UniqueConstraint("external_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_task_id: Mapped[int] = mapped_column(
        ForeignKey("protocol_tasks.id", ondelete="CASCADE")
    )
    assignment_id: Mapped[int | None] = mapped_column(ForeignKey("protocol_task_assignments.id"))
    bitrix_task_id: Mapped[int | None] = mapped_column(Integer())
    parent_bitrix_task_id: Mapped[int | None] = mapped_column(Integer())
    task_type: Mapped[str] = mapped_column(String(32))
    external_key: Mapped[str] = mapped_column(String(255))
    sync_status: Mapped[str] = mapped_column(String(32), default="pending")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    protocol_task: Mapped[ProtocolTask] = relationship(back_populates="bitrix_links")


class ProtocolTaskLink(TimestampMixin, Base):
    """Provider-neutral link between a protocol instruction and an external task."""

    __tablename__ = "protocol_task_links"
    __table_args__ = (UniqueConstraint("external_system", "external_task_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_task_id: Mapped[int] = mapped_column(
        ForeignKey("protocol_tasks.id", ondelete="CASCADE"), index=True
    )
    external_system: Mapped[str] = mapped_column(String(32), default="BITRIX24")
    external_task_id: Mapped[str] = mapped_column(String(255))
    external_task_url: Mapped[str | None] = mapped_column(String(1000))
    external_status: Mapped[str | None] = mapped_column(String(64))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    protocol_task: Mapped[ProtocolTask] = relationship(back_populates="external_links")


class TaskAssessment(Base):
    __tablename__ = "task_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_task_id: Mapped[int] = mapped_column(
        ForeignKey("protocol_tasks.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))
    overall_score: Mapped[int | None] = mapped_column(Integer())
    clarity_score: Mapped[int | None] = mapped_column(Integer())
    completeness_score: Mapped[int | None] = mapped_column(Integer())
    smart_score: Mapped[int | None] = mapped_column(Integer())
    acceptance_criteria_score: Mapped[int | None] = mapped_column(Integer())
    summary: Mapped[str | None] = mapped_column(Text())
    missing_information_json: Mapped[str | None] = mapped_column(Text())
    warnings_json: Mapped[str | None] = mapped_column(Text())
    recommendations_json: Mapped[str | None] = mapped_column(Text())
    suggested_title: Mapped[str | None] = mapped_column(String(500))
    suggested_description: Mapped[str | None] = mapped_column(Text())
    suggested_acceptance_criteria: Mapped[str | None] = mapped_column(Text())
    raw_response_json: Mapped[str | None] = mapped_column(Text())
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PublicationRun(Base):
    __tablename__ = "publication_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocols.id", ondelete="CASCADE"))
    gateway_type: Mapped[str] = mapped_column(String(64), default="fake")
    mode: Mapped[str] = mapped_column(String(32), default="demo")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_items: Mapped[int] = mapped_column(Integer(), default=0)
    successful_items: Mapped[int] = mapped_column(Integer(), default=0)
    failed_items: Mapped[int] = mapped_column(Integer(), default=0)
    created_by: Mapped[str | None] = mapped_column(String(255))
    error_summary: Mapped[str | None] = mapped_column(Text())
    operation_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    request_id: Mapped[str | None] = mapped_column(String(128), index=True)
    protocol: Mapped[Protocol] = relationship(back_populates="publication_runs")
    items: Mapped[list["PublicationItem"]] = relationship(back_populates="publication_run")


class PublicationItem(Base):
    __tablename__ = "publication_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    publication_run_id: Mapped[int] = mapped_column(
        ForeignKey("publication_runs.id", ondelete="CASCADE")
    )
    protocol_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("protocol_tasks.id", ondelete="SET NULL")
    )
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("protocol_task_assignments.id", ondelete="SET NULL")
    )
    external_key: Mapped[str] = mapped_column(String(255), index=True)
    parent_external_key: Mapped[str | None] = mapped_column(String(255))
    simulated_external_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    request_payload: Mapped[dict | None] = mapped_column(JSON())
    response_payload: Mapped[dict | None] = mapped_column(JSON())
    error_message: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    publication_run: Mapped[PublicationRun] = relationship(back_populates="items")
    protocol_task: Mapped[ProtocolTask | None] = relationship()


class EditPresence(Base):
    """Short-lived advisory editor presence; never locks a protocol."""

    __tablename__ = "edit_presence"
    __table_args__ = (UniqueConstraint("protocol_id", "username"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocols.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(255))
    request_id: Mapped[str | None] = mapped_column(String(128))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ImportSession(Base):
    __tablename__ = "import_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    file_size: Mapped[int] = mapped_column(Integer())
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    parser_type: Mapped[str] = mapped_column(String(64), default="universal")
    parser_id: Mapped[str] = mapped_column(String(64), default="universal")
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    parsed_payload: Mapped[dict | None] = mapped_column(JSON())
    warnings_payload: Mapped[list | None] = mapped_column(JSON())
    errors_payload: Mapped[list | None] = mapped_column(JSON())
    parse_history: Mapped[list | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    protocol_id: Mapped[int | None] = mapped_column(ForeignKey("protocols.id"))
    project: Mapped[Project] = relationship()
    protocol: Mapped[Protocol | None] = relationship()


class SavedReportView(Base):
    __tablename__ = "saved_report_views"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    owner: Mapped[str] = mapped_column(String(255), index=True)
    filters_json: Mapped[dict] = mapped_column(JSON(), default=dict)
    report_type: Mapped[str] = mapped_column(String(64), default="tasks")
    shared: Mapped[bool] = mapped_column(Boolean(), default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReportRun(Base):
    __tablename__ = "report_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_type: Mapped[str] = mapped_column(String(64), index=True)
    user: Mapped[str] = mapped_column(String(255), index=True)
    filters_json: Mapped[dict] = mapped_column(JSON(), default=dict)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_path: Mapped[str | None] = mapped_column(String(1000))
    file_url: Mapped[str | None] = mapped_column(String(1000))
    error_message: Mapped[str | None] = mapped_column(Text())


@event.listens_for(Session, "before_flush")
def create_default_participant_group(session: Session, _flush_context, _instances) -> None:
    """Ensure every protocol, regardless of its creation entry point, has the system group."""
    for obj in session.new:
        if isinstance(obj, Protocol) and not any(
            group.type == "attendees" for group in obj.participant_groups
        ):
            obj.participant_groups.append(
                ProtocolParticipantGroup(name="Присутствовали", type="attendees")
            )


@event.listens_for(Protocol, "after_insert")
def clear_orphaned_protocol_groups(_mapper, connection, target: Protocol) -> None:
    """Defend against SQLite clients that delete protocols with FK enforcement disabled."""
    connection.execute(
        ProtocolParticipantGroup.__table__.delete().where(
            ProtocolParticipantGroup.protocol_id == target.id
        )
    )
