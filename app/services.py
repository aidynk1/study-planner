import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import HTTPException, status

MAX_ACTIVE_TASKS = 50


def get_connection(database_path: str) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def initialize_database(database_path: str) -> None:
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
                description TEXT NOT NULL DEFAULT '',
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'planned'
                    CHECK(status IN ('planned', 'in_progress', 'done')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_values(task: sqlite3.Row) -> dict[str, Any]:
    return dict(task)


def _normalize_title(title: str) -> str:
    normalized_title = title.strip()
    if not normalized_title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Название задачи не может быть пустым.",
        )
    return normalized_title


def _ensure_active_task_limit(
    connection: sqlite3.Connection,
    task_status: str,
    excluding_task_id: int | None = None,
) -> None:
    if task_status == "done":
        return

    query = "SELECT COUNT(*) FROM tasks WHERE status != 'done'"
    parameters: tuple[int, ...] = ()
    if excluding_task_id is not None:
        query += " AND id != ?"
        parameters = (excluding_task_id,)

    active_count = connection.execute(query, parameters).fetchone()[0]
    if active_count >= MAX_ACTIVE_TASKS:
        connection.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Достигнут лимит в 50 активных задач. Завершите задачу перед добавлением новой.",
        )


def list_tasks(
    connection: sqlite3.Connection, task_status: str | None = None
) -> list[dict[str, Any]]:
    if task_status is None:
        rows = connection.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC, id DESC"
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC, id DESC",
            (task_status,),
        ).fetchall()
    return [_task_values(row) for row in rows]


def create_task(
    connection: sqlite3.Connection, task: dict[str, Any]
) -> dict[str, Any]:
    title = _normalize_title(task["title"])
    connection.execute("BEGIN IMMEDIATE")
    _ensure_active_task_limit(connection, task["status"])
    timestamp = _utc_now()
    cursor = connection.execute(
        """
        INSERT INTO tasks (title, description, due_date, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            task["description"],
            task["due_date"].isoformat() if task["due_date"] else None,
            task["status"],
            timestamp,
            timestamp,
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _task_values(row)


def get_task(connection: sqlite3.Connection, task_id: int) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Задача не найдена.")
    return _task_values(row)


def replace_task(
    connection: sqlite3.Connection, task_id: int, task: dict[str, Any]
) -> dict[str, Any]:
    title = _normalize_title(task["title"])
    connection.execute("BEGIN IMMEDIATE")
    existing = connection.execute(
        "SELECT id FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Задача не найдена.")
    _ensure_active_task_limit(connection, task["status"], excluding_task_id=task_id)
    connection.execute(
        """
        UPDATE tasks
        SET title = ?, description = ?, due_date = ?, status = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            title,
            task["description"],
            task["due_date"].isoformat() if task["due_date"] else None,
            task["status"],
            _utc_now(),
            task_id,
        ),
    )
    connection.commit()
    return get_task(connection, task_id)


def update_task(
    connection: sqlite3.Connection, task_id: int, changes: dict[str, Any]
) -> dict[str, Any]:
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Укажите хотя бы одно поле для изменения.",
        )
    if "title" in changes:
        if changes["title"] is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Название задачи не может быть пустым.",
            )
        changes["title"] = _normalize_title(changes["title"])
    if changes.get("description") is None and "description" in changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Описание должно быть строкой.",
        )
    if changes.get("status") is None and "status" in changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Укажите допустимый статус задачи.",
        )
    if "due_date" in changes:
        changes["due_date"] = (
            changes["due_date"].isoformat() if changes["due_date"] else None
        )

    connection.execute("BEGIN IMMEDIATE")
    existing = connection.execute(
        "SELECT status FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Задача не найдена.")
    new_status = changes.get("status", existing["status"])
    _ensure_active_task_limit(connection, new_status, excluding_task_id=task_id)

    assignments = ", ".join(f"{field} = ?" for field in changes)
    values = list(changes.values())
    values.extend((_utc_now(), task_id))
    connection.execute(
        f"UPDATE tasks SET {assignments}, updated_at = ? WHERE id = ?", values
    )
    connection.commit()
    return get_task(connection, task_id)


def delete_task(connection: sqlite3.Connection, task_id: int) -> None:
    connection.execute("BEGIN IMMEDIATE")
    cursor = connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Задача не найдена.")
    connection.commit()


def get_study_focus(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT * FROM tasks
        WHERE status != 'done'
        ORDER BY
            CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
            due_date ASC,
            CASE WHEN status = 'in_progress' THEN 0 ELSE 1 END,
            created_at ASC,
            id ASC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Нет активных задач, для которых можно выбрать фокус.",
        )

    task = _task_values(row)
    due_date = date.fromisoformat(task["due_date"]) if task["due_date"] else None
    if due_date is not None and due_date <= date.today():
        reason = "Дедлайн этой задачи уже наступил или наступает сегодня."
    elif task["status"] == "in_progress":
        reason = "Задача уже начата — продолжите её."
    elif due_date is not None:
        reason = "У этой активной задачи самый близкий дедлайн."
    else:
        reason = "У задачи нет дедлайна; она выбрана после задач со сроком."
    return {"task": task, "reason": reason}
