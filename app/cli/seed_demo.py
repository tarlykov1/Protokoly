from datetime import date

from sqlalchemy import select

from app.db.models.domain import (
    Block,
    Direction,
    Employee,
    EmployeeAlias,
    EmployeeList,
    EmployeeListMember,
    Project,
    Protocol,
    ProtocolSection,
    ProtocolTask,
    ProtocolTaskAssignment,
)
from app.db.session import SessionLocal

DEMO = "demo-mvp"


def get_or_create(db, model, defaults=None, **kw):
    obj = db.scalar(select(model).filter_by(**kw))
    if obj:
        return obj
    obj = model(**kw, **(defaults or {}))
    db.add(obj)
    db.flush()
    return obj


def seed():
    with SessionLocal() as db:
        tech = get_or_create(
            db,
            Employee,
            email="demo.tech@example.test",
            defaults=dict(
                full_name="Технический пользователь",
                last_name="Пользователь",
                first_name="Технический",
                bitrix_user_id=9000,
                source_system=DEMO,
                is_available_in_bitrix=True,
            ),
        )
        project = get_or_create(
            db,
            Project,
            code="DEMO-MVP",
            defaults=dict(
                name="Демонстрационный проект",
                description="Автономная демоверсия",
                bitrix_group_id=100,
                technical_user_id=tech.bitrix_user_id,
                numbering_prefix="DEMO",
            ),
        )
        d1 = get_or_create(
            db,
            Direction,
            project_id=project.id,
            code="ORG",
            defaults=dict(name="Организация", sort_order=1),
        )
        d2 = get_or_create(
            db, Direction, project_id=project.id, code="IT", defaults=dict(name="ИТ", sort_order=2)
        )
        b1 = get_or_create(
            db,
            Block,
            project_id=project.id,
            direction_id=d1.id,
            code="PLAN",
            defaults=dict(name="Планирование"),
        )
        b2 = get_or_create(
            db,
            Block,
            project_id=project.id,
            direction_id=d2.id,
            code="QA",
            defaults=dict(name="Качество"),
        )
        names = [
            "Иванов Иван Иванович",
            "Петров Петр Петрович",
            "Сидоров Сергей Сергеевич",
            "Кузнецова Анна Олеговна",
            "Смирнова Мария Игоревна",
            "Васильев Алексей Павлович",
            "Морозов Дмитрий Андреевич",
            "Новикова Елена Викторовна",
            "Федоров Николай Романович",
            "Орлова Ольга Сергеевна",
        ]
        emps = []
        for i, n in enumerate(names, 1):
            emps.append(
                get_or_create(
                    db,
                    Employee,
                    email=f"demo.user{i}@example.test",
                    defaults=dict(
                        full_name=n,
                        last_name=n.split()[0],
                        first_name=n.split()[1],
                        middle_name=n.split()[2],
                        bitrix_user_id=(1000 + i if i < 10 else None),
                        source_system=DEMO,
                        is_available_in_bitrix=i < 10,
                    ),
                )
            )
        for e in emps[:4]:
            get_or_create(
                db,
                EmployeeAlias,
                employee_id=e.id,
                normalized_alias=e.last_name.lower(),
                defaults=dict(alias=e.last_name, source=DEMO),
            )
        l1 = get_or_create(
            db,
            EmployeeList,
            project_id=project.id,
            name="Демо: рабочая группа",
            defaults=dict(description=DEMO),
        )
        l2 = get_or_create(
            db,
            EmployeeList,
            project_id=project.id,
            name="Демо: контроль",
            defaults=dict(description=DEMO),
        )
        for idx, e in enumerate(emps[:5]):
            get_or_create(
                db,
                EmployeeListMember,
                employee_list_id=l1.id,
                employee_id=e.id,
                defaults=dict(sort_order=idx),
            )
        for idx, e in enumerate(emps[5:9]):
            get_or_create(
                db,
                EmployeeListMember,
                employee_list_id=l2.id,
                employee_id=e.id,
                defaults=dict(sort_order=idx),
            )
        proto = get_or_create(
            db,
            Protocol,
            project_id=project.id,
            number="DEMO-001",
            defaults=dict(
                title="Демонстрационный протокол",
                meeting_date=date(2026, 7, 21),
                status="validation_required",
                source_type=DEMO,
                created_by="seed_demo",
            ),
        )
        s1 = get_or_create(
            db,
            ProtocolSection,
            protocol_id=proto.id,
            title="Запуск проекта",
            defaults=dict(direction_id=d1.id, block_id=b1.id, sort_order=1),
        )
        s2 = get_or_create(
            db,
            ProtocolSection,
            protocol_id=proto.id,
            title="Качество",
            defaults=dict(direction_id=d2.id, block_id=b2.id, sort_order=2),
        )
        task_defs = [
            (
                "1",
                "Подготовить план демонстрации",
                date(2026, 7, 31),
                False,
                s1,
                [emps[0], emps[1]],
            ),
            (
                "2",
                "Сформировать корневую задачу и подзадачи",
                date(2026, 8, 5),
                True,
                s1,
                [emps[2], emps[3]],
            ),
            ("3", "Уточнить поручение без срока", None, False, s2, [emps[4]]),
            ("4", "Поручение с нераспознанным исполнителем", date(2026, 8, 10), False, s2, []),
            (
                "5",
                "Самостоятельная задача для исполнителя без Bitrix ID",
                date(2026, 8, 15),
                False,
                s2,
                [emps[-1]],
            ),
        ]
        for num, title, deadline, subs, sec, assignees in task_defs:
            t = get_or_create(
                db,
                ProtocolTask,
                protocol_id=proto.id,
                number=num,
                defaults=dict(
                    section_id=sec.id,
                    title=title,
                    description=title,
                    acceptance_criteria="Результат согласован",
                    deadline=deadline,
                    priority="normal",
                    create_as_subtasks=subs,
                    status="draft",
                    original_text=f"{num}. {title}",
                ),
            )
            for idx, e in enumerate(assignees, 1):
                get_or_create(
                    db,
                    ProtocolTaskAssignment,
                    protocol_task_id=t.id,
                    employee_id=e.id,
                    defaults=dict(sort_order=idx),
                )
        db.commit()
        print("Demo data ready")


if __name__ == "__main__":
    seed()
