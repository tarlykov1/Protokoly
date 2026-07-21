from sqlalchemy import delete, select

from app.db.models.domain import (
    BitrixTaskLink,
    Block,
    Direction,
    Employee,
    EmployeeAlias,
    EmployeeList,
    EmployeeListMember,
    ImportSession,
    Project,
    Protocol,
    ProtocolSection,
    ProtocolTask,
    ProtocolTaskAssignment,
    PublicationItem,
    PublicationRun,
    TaskAssessment,
)
from app.db.session import SessionLocal


def reset():
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == "DEMO-MVP"))
        if project:
            protocol_ids = select(Protocol.id).where(Protocol.project_id == project.id)
            task_ids = select(ProtocolTask.id).where(ProtocolTask.protocol_id.in_(protocol_ids))
            run_ids = select(PublicationRun.id).where(PublicationRun.protocol_id.in_(protocol_ids))
            db.execute(delete(PublicationItem).where(PublicationItem.publication_run_id.in_(run_ids)))
            db.execute(delete(PublicationRun).where(PublicationRun.protocol_id.in_(protocol_ids)))
            db.execute(delete(TaskAssessment).where(TaskAssessment.protocol_task_id.in_(task_ids)))
            db.execute(delete(BitrixTaskLink).where(BitrixTaskLink.protocol_task_id.in_(task_ids)))
            db.execute(delete(ProtocolTaskAssignment).where(ProtocolTaskAssignment.protocol_task_id.in_(task_ids)))
            db.execute(delete(ProtocolTask).where(ProtocolTask.protocol_id.in_(protocol_ids)))
            db.execute(delete(ProtocolSection).where(ProtocolSection.protocol_id.in_(protocol_ids)))
            db.execute(delete(ImportSession).where(ImportSession.project_id == project.id))
            db.execute(delete(Protocol).where(Protocol.project_id == project.id))
            db.execute(delete(EmployeeListMember).where(EmployeeListMember.employee_list_id.in_(select(EmployeeList.id).where(EmployeeList.project_id == project.id))))
            db.execute(delete(EmployeeList).where(EmployeeList.project_id == project.id))
            db.execute(delete(Block).where(Block.project_id == project.id))
            db.execute(delete(Direction).where(Direction.project_id == project.id))
            db.delete(project)
        demo_employee_ids = select(Employee.id).where(Employee.source_system == "demo-mvp")
        db.execute(delete(EmployeeAlias).where(EmployeeAlias.employee_id.in_(demo_employee_ids)))
        db.execute(delete(Employee).where(Employee.source_system == "demo-mvp"))
        db.commit()
        print("Demo data removed")


if __name__ == "__main__":
    reset()
