import sqlite3
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import create_app


def make_client(tmp_path):
    app = create_app(str(tmp_path / "test.db"))
    return TestClient(app)


def test_task_crud_and_filter(tmp_path):
    with make_client(tmp_path) as client:
        created = client.post(
            "/api/tasks",
            json={
                "title": "Подготовить доклад",
                "description": "Найти источники",
                "due_date": "2026-11-01",
            },
        )
        assert created.status_code == 201
        task = created.json()
        assert task["title"] == "Подготовить доклад"
        assert task["status"] == "planned"
        assert task["due_date"] == "2026-11-01"

        task_id = task["id"]
        with sqlite3.connect(tmp_path / "test.db") as connection:
            assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert client.get(f"/api/tasks/{task_id}").json()["id"] == task_id

        replaced = client.put(
            f"/api/tasks/{task_id}",
            json={
                "title": "Сдать доклад",
                "description": "Добавить выводы",
                "due_date": "2026-11-03",
                "status": "in_progress",
            },
        )
        assert replaced.status_code == 200
        assert replaced.json()["title"] == "Сдать доклад"
        assert replaced.json()["description"] == "Добавить выводы"
        assert replaced.json()["due_date"] == "2026-11-03"
        assert replaced.json()["status"] == "in_progress"
        with sqlite3.connect(tmp_path / "test.db") as connection:
            assert connection.execute(
                "SELECT title FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()[0] == "Сдать доклад"

        replaced_with_defaults = client.put(
            f"/api/tasks/{task_id}", json={"title": "Сданный доклад"}
        )
        assert replaced_with_defaults.status_code == 200
        assert replaced_with_defaults.json()["description"] == ""
        assert replaced_with_defaults.json()["due_date"] is None
        assert replaced_with_defaults.json()["status"] == "planned"

        updated = client.patch(
            f"/api/tasks/{task_id}",
            json={
                "title": "Сдать доклад",
                "status": "in_progress",
                "due_date": None,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["title"] == "Сдать доклад"
        assert updated.json()["status"] == "in_progress"
        assert updated.json()["due_date"] is None
        assert len(client.get("/api/tasks?status=in_progress").json()) == 1
        assert client.get("/api/tasks?status=done").json() == []

        assert client.delete(f"/api/tasks/{task_id}").status_code == 204
        assert client.get(f"/api/tasks/{task_id}").status_code == 404
        with sqlite3.connect(tmp_path / "test.db") as connection:
            assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_invalid_task_data_is_rejected(tmp_path):
    with make_client(tmp_path) as client:
        assert client.post("/api/tasks", json={"title": "   "}).status_code == 422
        assert client.post(
            "/api/tasks", json={"title": "Задача", "status": "unknown"}
        ).status_code == 422
        assert client.patch("/api/tasks/999", json={}).status_code == 422
        assert client.put(
            "/api/tasks/999", json={"title": "Несуществующая"}
        ).status_code == 404
        created = client.post("/api/tasks", json={"title": "Задача"}).json()
        task_id = created["id"]
        assert client.patch(
            f"/api/tasks/{task_id}", json={"description": None}
        ).status_code == 422
        assert client.patch(
            f"/api/tasks/{task_id}", json={"status": None}
        ).status_code == 422
        assert client.put(
            f"/api/tasks/{task_id}", json={"title": "   "}
        ).status_code == 422


def test_active_task_limit_is_enforced(tmp_path):
    with make_client(tmp_path) as client:
        task_ids = []
        for task_number in range(50):
            response = client.post(
                "/api/tasks", json={"title": f"Задача {task_number}"}
            )
            assert response.status_code == 201
            task_ids.append(response.json()["id"])

        assert client.post(
            "/api/tasks", json={"title": "Лишняя задача"}
        ).status_code == 409
        assert client.patch(
            f"/api/tasks/{task_ids[0]}", json={"status": "done"}
        ).status_code == 200
        assert client.post(
            "/api/tasks", json={"title": "Новая задача"}
        ).status_code == 201
        assert client.patch(
            f"/api/tasks/{task_ids[0]}", json={"status": "planned"}
        ).status_code == 409


def test_study_focus_prioritizes_earliest_deadline(tmp_path):
    with make_client(tmp_path) as client:
        later_deadline = (date.today() + timedelta(days=20)).isoformat()
        earlier_deadline = (date.today() + timedelta(days=10)).isoformat()
        client.post(
            "/api/tasks",
            json={"title": "Позже", "due_date": later_deadline},
        )
        first = client.post(
            "/api/tasks",
            json={"title": "Ближайший срок", "due_date": earlier_deadline},
        )
        client.post("/api/tasks", json={"title": "Без срока"})

        focus = client.get("/api/tasks/focus")
        assert focus.status_code == 200
        assert focus.json()["task"]["id"] == first.json()["id"]
        assert "близкий дедлайн" in focus.json()["reason"]

        assert client.patch(
            f"/api/tasks/{first.json()['id']}", json={"status": "done"}
        ).status_code == 200
        assert client.get("/api/tasks/focus").json()["task"]["title"] == "Позже"

        assert client.patch(
            "/api/tasks/1", json={"status": "done"}
        ).status_code == 200
        assert client.patch(
            "/api/tasks/3", json={"status": "done"}
        ).status_code == 200
        assert client.get("/api/tasks/focus").status_code == 404


def test_homepage_and_api_documentation_are_available(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get("/").status_code == 200
        homepage = client.get("/").text
        assert "Учебный планер" in homepage
        assert 'id="study-focus"' in homepage
        assert client.get("/docs").status_code == 200
