import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

TaskStatus = Literal["planned", "in_progress", "done"]
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    due_date: date | None = None
    status: TaskStatus = "planned"


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    due_date: date | None = None
    status: TaskStatus | None = None


class TaskRead(BaseModel):
    id: int
    title: str
    description: str
    due_date: date | None
    status: TaskStatus
    created_at: datetime
    updated_at: datetime


def get_connection(database_path: str):
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def task_values(task: sqlite3.Row) -> dict:
    return dict(task)


def create_app(database_path: str | None = None) -> FastAPI:
    resolved_database_path = database_path or os.getenv(
        "DATABASE_PATH", str(PROJECT_ROOT / "data" / "tasks.db")
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize_database(resolved_database_path)
        yield

    application = FastAPI(
        title="Учебный планер API",
        description="API для создания и отслеживания учебных задач.",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.database_path = resolved_database_path
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def database_dependency():
        yield from get_connection(application.state.database_path)

    @application.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/api/tasks", response_model=list[TaskRead])
    def list_tasks(
        connection: sqlite3.Connection = Depends(database_dependency),
        task_status: Annotated[TaskStatus | None, Query(alias="status")] = None,
    ):
        if task_status is None:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC, id DESC"
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC, id DESC",
                (task_status,),
            ).fetchall()
        return [task_values(row) for row in rows]

    @application.post(
        "/api/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED
    )
    def create_task(
        task: TaskCreate,
        connection: sqlite3.Connection = Depends(database_dependency),
    ):
        title = task.title.strip()
        if not title:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Название задачи не может быть пустым.",
            )
        timestamp = utc_now()
        cursor = connection.execute(
            """
            INSERT INTO tasks (title, description, due_date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                task.description,
                task.due_date.isoformat() if task.due_date else None,
                task.status,
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return task_values(row)

    @application.get("/api/tasks/{task_id}", response_model=TaskRead)
    def get_task(
        task_id: int,
        connection: sqlite3.Connection = Depends(database_dependency),
    ):
        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Задача не найдена.")
        return task_values(row)

    @application.patch("/api/tasks/{task_id}", response_model=TaskRead)
    def update_task(
        task_id: int,
        task: TaskUpdate,
        connection: sqlite3.Connection = Depends(database_dependency),
    ):
        changes = task.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(
                status_code=422,
                detail="Укажите хотя бы одно поле для изменения.",
            )
        if "title" in changes:
            if changes["title"] is None or not changes["title"].strip():
                raise HTTPException(
                    status_code=422,
                    detail="Название задачи не может быть пустым.",
                )
            changes["title"] = changes["title"].strip()
        if changes.get("description") is None and "description" in changes:
            raise HTTPException(
                status_code=422,
                detail="Описание должно быть строкой.",
            )
        if changes.get("status") is None and "status" in changes:
            raise HTTPException(
                status_code=422,
                detail="Укажите допустимый статус задачи.",
            )
        if "due_date" in changes:
            changes["due_date"] = (
                changes["due_date"].isoformat() if changes["due_date"] else None
            )

        assignments = ", ".join(f"{field} = ?" for field in changes)
        values = list(changes.values())
        values.extend((utc_now(), task_id))
        cursor = connection.execute(
            f"UPDATE tasks SET {assignments}, updated_at = ? WHERE id = ?",
            values,
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Задача не найдена.")
        connection.commit()
        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return task_values(row)

    @application.delete(
        "/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT
    )
    def delete_task(
        task_id: int,
        connection: sqlite3.Connection = Depends(database_dependency),
    ):
        cursor = connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Задача не найдена.")
        connection.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return application


app = create_app()
