import os
import sqlite3
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Iterator, Literal

from fastapi import Depends, FastAPI, Query, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import services

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


class TaskReplace(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    due_date: date | None = None
    status: TaskStatus = "planned"


class TaskRead(BaseModel):
    id: int
    title: str
    description: str
    due_date: date | None
    status: TaskStatus
    created_at: datetime
    updated_at: datetime


class TaskFocus(BaseModel):
    task: TaskRead
    reason: str


def create_app(database_path: str | None = None) -> FastAPI:
    resolved_database_path = database_path or os.getenv(
        "DATABASE_PATH", str(PROJECT_ROOT / "data" / "tasks.db")
    )
    temporary_database_directory = None
    if resolved_database_path == ":memory:":
        temporary_database_directory = tempfile.TemporaryDirectory(
            prefix="study-planner-"
        )
        resolved_database_path = str(
            Path(temporary_database_directory.name) / "tasks.db"
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            services.initialize_database(resolved_database_path)
            yield
        finally:
            if temporary_database_directory is not None:
                temporary_database_directory.cleanup()

    application = FastAPI(
        title="Учебный планер API",
        description="API для создания и отслеживания учебных задач.",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.database_path = resolved_database_path
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def database_dependency() -> Iterator[sqlite3.Connection]:
        yield from services.get_connection(application.state.database_path)

    @application.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/api/tasks", response_model=list[TaskRead])
    def list_tasks(
        connection: sqlite3.Connection = Depends(database_dependency),
        task_status: Annotated[TaskStatus | None, Query(alias="status")] = None,
    ):
        return services.list_tasks(connection, task_status)

    @application.post(
        "/api/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED
    )
    def create_task(
        task: TaskCreate,
        connection: sqlite3.Connection = Depends(database_dependency),
    ):
        return services.create_task(connection, task.model_dump())

    @application.get("/api/tasks/focus", response_model=TaskFocus)
    def study_focus(
        connection: sqlite3.Connection = Depends(database_dependency),
    ):
        return services.get_study_focus(connection)

    @application.get("/api/tasks/{task_id}", response_model=TaskRead)
    def get_task(
        task_id: int,
        connection: sqlite3.Connection = Depends(database_dependency),
    ):
        return services.get_task(connection, task_id)

    @application.put("/api/tasks/{task_id}", response_model=TaskRead)
    def replace_task(
        task_id: int,
        task: TaskReplace,
        connection: sqlite3.Connection = Depends(database_dependency),
    ):
        return services.replace_task(connection, task_id, task.model_dump())

    @application.patch("/api/tasks/{task_id}", response_model=TaskRead)
    def update_task(
        task_id: int,
        task: TaskUpdate,
        connection: sqlite3.Connection = Depends(database_dependency),
    ):
        return services.update_task(
            connection, task_id, task.model_dump(exclude_unset=True)
        )

    @application.delete(
        "/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT
    )
    def delete_task(
        task_id: int,
        connection: sqlite3.Connection = Depends(database_dependency),
    ):
        services.delete_task(connection, task_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return application


app = create_app()
