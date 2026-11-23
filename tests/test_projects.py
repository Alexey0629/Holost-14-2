"""Список проектів, налаштування, безпека."""


def test_index_and_project_pages(client, project_id):
    assert client.get("/").status_code == 200
    page = client.get(f"/projects/{project_id}")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    for label in ("Папки", "Опис", "Код", "Структура БД", "Використання", "API", "Пошук", "Візуал",
                  "Оновлення з проду", "Історія змін", "Падіння, помилки", "Структура проекту", "Тести + Git"):
        assert label in html
    assert client.get("/projects/9999").status_code == 404


def test_add_project_reads_readme_and_stack(client, project_id, sample_project):
    data = client.get("/api/projects").get_json()
    [p] = data["projects"]
    assert p["name"] == "demo"
    assert p["short_desc"] == "Демо-проект для тестів Holost."
    assert {"Python", "Flask", "SQLAlchemy"} <= set(p["stack"])
    # повторне додавання — 409 з id існуючого
    res = client.post("/api/projects", json={"path": str(sample_project)})
    assert res.status_code == 409 and res.get_json()["id"] == project_id


def test_add_project_missing_folder(client, tmp_path):
    res = client.post("/api/projects", json={"path": str(tmp_path / "nope")})
    assert res.status_code == 400


def test_scan_roots(client, sample_project, tmp_path):
    other = tmp_path / "projects" / "group" / "node-app"
    other.mkdir(parents=True)
    (other / "package.json").write_text('{"dependencies": {"express": "4"}}')
    (tmp_path / "projects" / "not-a-project").mkdir()

    assert client.post("/api/scan").status_code == 400  # папки ще не вказані
    res = client.put("/api/settings", json={"roots": [str(tmp_path / "projects")]})
    assert res.get_json()["missing"] == []
    res = client.post("/api/scan").get_json()
    assert res["found"] == 2
    names = sorted(p["name"] for p in client.get("/api/projects").get_json()["projects"])
    assert names == ["demo", "node-app"]
    # повторний скан нічого не дублює
    assert client.post("/api/scan").get_json()["added"] == []


def test_update_description_records_history(client, project_id):
    res = client.put(f"/api/projects/{project_id}", json={"full_desc": "# Опис\nНовий", "favorite": True,
                                                          "path": "/etc"})
    data = res.get_json()
    assert data["full_desc"] == "# Опис\nНовий"
    assert data["favorite"] == 1
    assert data["path"] != "/etc"  # шлях не редагується через API
    changes = client.get(f"/api/projects/{project_id}/changes").get_json()["changes"]
    assert changes[0]["kind"] == "description"


def test_csrf_required_for_changes(client, project_id):
    res = client.raw.put(f"/api/projects/{project_id}", json={"name": "hacked"})
    assert res.status_code == 403
    res = client.raw.post("/api/scan", headers={"X-CSRF-Token": "wrong"})
    assert res.status_code == 403


def test_foreign_host_rejected(client):
    res = client.raw.get("/", headers={"Host": "evil.example.com"})
    assert res.status_code == 403
    assert client.raw.get("/", headers={"Host": "127.0.0.1:5000"}).status_code == 200


def test_delete_project_keeps_files(client, project_id, sample_project):
    assert client.delete(f"/api/projects/{project_id}").status_code == 200
    assert client.get("/api/projects").get_json()["projects"] == []
    assert (sample_project / "app.py").exists()


def test_summary_has_git_info(client, project_id):
    s = client.get(f"/api/projects/{project_id}/summary").get_json()
    assert s["git"]["is_repo"] and s["git"]["branch"] == "main"
    assert s["git"]["last_commit"]["subject"] == "Initial commit"
