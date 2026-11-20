from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, Task, User, create_database_engine
from seed import seed_database


def test_seed_creates_users_tasks_and_relationships(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'project.db').as_posix()}"

    assert seed_database(database_url) == (3, 12)

    engine = create_database_engine(database_url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 3
        assert session.scalar(select(func.count()).select_from(Task)) == 12

        first_task = session.scalar(
            select(Task).where(Task.title == "Подготовить доклад по биологии")
        )
        assert first_task is not None
        assert first_task.user.email == "anna@example.com"
        assert first_task.due_date == date(2026, 11, 10)

    engine.dispose()


def test_seed_refuses_to_overwrite_existing_data(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'project.db').as_posix()}"
    seed_database(database_url)

    with pytest.raises(RuntimeError, match="will not overwrite"):
        seed_database(database_url)


def test_deleting_user_cascades_to_tasks(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'cascade.db').as_posix()}"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(name="Тест", email="test@example.com")
        user.tasks.append(Task(title="Тестовая задача"))
        session.add(user)
        session.commit()
        user_id = user.id

        session.delete(user)
        session.commit()

        assert session.scalar(
            select(func.count()).select_from(Task).where(Task.user_id == user_id)
        ) == 0

    engine.dispose()


def test_task_status_is_limited_to_supported_values(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'status.db').as_posix()}"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(name="Тест", email="status@example.com")
        session.add(user)
        session.flush()
        session.add(Task(user_id=user.id, title="Некорректный статус", status="blocked"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    engine.dispose()
