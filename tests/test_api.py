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
        assert client.get(f"/api/tasks/{task_id}").json()["id"] == task_id

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


def test_invalid_task_data_is_rejected(tmp_path):
    with make_client(tmp_path) as client:
        assert client.post("/api/tasks", json={"title": "   "}).status_code == 422
        assert client.post(
            "/api/tasks", json={"title": "Задача", "status": "unknown"}
        ).status_code == 422
        assert client.patch("/api/tasks/999", json={}).status_code == 422
        created = client.post("/api/tasks", json={"title": "Задача"}).json()
        task_id = created["id"]
        assert client.patch(
            f"/api/tasks/{task_id}", json={"description": None}
        ).status_code == 422
        assert client.patch(
            f"/api/tasks/{task_id}", json={"status": None}
        ).status_code == 422


def test_homepage_and_api_documentation_are_available(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get("/").status_code == 200
        assert "Учебный планер" in client.get("/").text
        assert client.get("/docs").status_code == 200
