import os
from datetime import date
from pathlib import Path

from sqlalchemy import URL, func, select
from sqlalchemy.orm import Session

from app.models import Base, Task, User, create_database_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    URL.create(
        "sqlite",
        database=str(Path(__file__).resolve().with_name("project.db")),
    ),
)

USER_DATA = (
    ("Анна Смирнова", "anna@example.com"),
    ("Илья Петров", "ilya@example.com"),
    ("Мария Ким", "maria@example.com"),
)

TASK_DATA = (
    (0, "Подготовить доклад по биологии",
     "Собрать источники и сделать план выступления.", date(2026, 11, 10), "in_progress"),
    (0, "Решить задачи по алгебре", "Выполнить упражнения из главы 4.",
     date(2026, 11, 12), "planned"),
    (0, "Прочитать главы по истории",
     "Подготовить краткий конспект.", date(2026, 11, 14), "planned"),
    (0, "Сдать лабораторную по химии",
     "Оформить результаты эксперимента.", date(2026, 11, 7), "done"),
    (1, "Сделать презентацию по физике",
     "Подготовить 8–10 слайдов.", date(2026, 11, 15), "in_progress"),
    (1, "Повторить английскую грамматику",
     "Повторить времена группы Perfect.", date(2026, 11, 18), "planned"),
    (1, "Сдать эссе по литературе", "Тема: образ героя в романе.", date(2026, 11, 8), "done"),
    (1, "Подготовиться к контрольной по геометрии",
     "Разобрать теоремы и решить варианты.", date(2026, 11, 20), "planned"),
    (2, "Сверстать страницу проекта", "Проверить адаптивную версию.",
     date(2026, 11, 11), "in_progress"),
    (2, "Пройти тест по информатике",
     "Повторить алгоритмы и структуры данных.", date(2026, 11, 13), "planned"),
    (2, "Сдать практическую по географии",
     "Заполнить контурную карту.", date(2026, 11, 6), "done"),
    (2, "Подготовить конспект по обществознанию",
     "Тема: права и обязанности граждан.", date(2026, 11, 19), "planned"),
)


def seed_database(database_url: str | URL = DATABASE_URL) -> tuple[int, int]:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            user_count = session.scalar(select(func.count()).select_from(User)) or 0
            task_count = session.scalar(select(func.count()).select_from(Task)) or 0
            if user_count or task_count:
                raise RuntimeError(
                    "Database already contains data; seed.py will not overwrite it."
                )

            users = [User(name=name, email=email) for name, email in USER_DATA]
            tasks = [
                Task(
                    user=users[user_index],
                    title=title,
                    description=description,
                    due_date=due_date,
                    status=task_status,
                )
                for user_index, title, description, due_date, task_status in TASK_DATA
            ]
            session.add_all([*users, *tasks])
            session.commit()
    finally:
        engine.dispose()

    return len(users), len(tasks)


def main() -> None:
    user_count, task_count = seed_database()
    print(f"Seeded {user_count} users and {task_count} tasks into project.db.")


if __name__ == "__main__":
    main()
