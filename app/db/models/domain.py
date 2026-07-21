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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


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
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    protocol_type: Mapped[str] = mapped_column(String(64), default="protocol")
    title: Mapped[str] = mapped_column(String(500))
    number: Mapped[str | None] = mapped_column(String(64))
    meeting_date: Mapped[date | None] = mapped_column(Date())
    status: Mapped[str] = mapped_column(String(32), default="draft")
    source_type: Mapped[str] = mapped_column(String(32), default="manual")
    source_filename: Mapped[str | None] = mapped_column(String(255))
    source_file_path: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str | None] = mapped_column(String(255))
    project: Mapped[Project] = relationship(back_populates="protocols")
    tasks: Mapped[list["ProtocolTask"]] = relationship(back_populates="protocol")


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
    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocols.id", ondelete="CASCADE"))
    section_id: Mapped[int | None] = mapped_column(ForeignKey("protocol_sections.id"))
    number: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text())
    acceptance_criteria: Mapped[str | None] = mapped_column(Text())
    deadline: Mapped[date | None] = mapped_column(Date())
    priority: Mapped[str | None] = mapped_column(String(32))
    create_as_subtasks: Mapped[bool] = mapped_column(Boolean(), default=False)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    original_text: Mapped[str | None] = mapped_column(Text())
    source_page: Mapped[int | None] = mapped_column(Integer())
    source_paragraph: Mapped[int | None] = mapped_column(Integer())
    source_table: Mapped[int | None] = mapped_column(Integer())
    protocol: Mapped[Protocol] = relationship(back_populates="tasks")
    assignments: Mapped[list["ProtocolTaskAssignment"]] = relationship(
        back_populates="protocol_task"
    )
    bitrix_links: Mapped[list["BitrixTaskLink"]] = relationship(back_populates="protocol_task")


class ProtocolTaskAssignment(Base):
    __tablename__ = "protocol_task_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_task_id: Mapped[int] = mapped_column(
        ForeignKey("protocol_tasks.id", ondelete="CASCADE")
    )
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    source_employee_list_id: Mapped[int | None] = mapped_column(ForeignKey("employee_lists.id"))
    individual_title: Mapped[str | None] = mapped_column(String(500))
    individual_description: Mapped[str | None] = mapped_column(Text())
    individual_acceptance_criteria: Mapped[str | None] = mapped_column(Text())
    individual_deadline: Mapped[date | None] = mapped_column(Date())
    individual_priority: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer(), default=0)
    protocol_task: Mapped[ProtocolTask] = relationship(back_populates="assignments")
    employee: Mapped[Employee | None] = relationship()


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
