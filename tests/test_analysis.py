"""Структура БД, структура використання, API-ендпоінти."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from allprojects.services import dbschema


def test_db_overview(client, project_id):
    d = client.get(f"/api/projects/{project_id}/db").get_json()

    [sqlite_db] = d["sqlite"]
    assert sqlite_db["path"] == "data.db"
    tables = {t["name"]: t for t in sqlite_db["tables"]}
    assert tables["users"]["rows"] == 2
    assert tables["posts"]["foreign_keys"] == [{"from": "user_id", "table": "users", "to": "id"}]
    assert tables["posts"]["indexes"][0]["columns"] == ["user_id"]

    [sql_file] = d["sql_files"]
    orders = sql_file["tables"][0]
    assert orders["name"] == "orders"
    cols = {c["name"]: c for c in orders["columns"]}
    assert cols["id"]["pk"] and cols["user_id"]["notnull"]
    assert cols["total"]["type"] == "NUMERIC(10, 2)"
    assert orders["foreign_keys"] == [{"from": "user_id", "table": "users", "to": "id"}]

    models = {m["class"]: m for m in d["models"]}
    assert models["User"]["table"] == "users"
    assert models["User"]["relationships"] == [{"name": "posts", "target": "Post"}]
    assert {f["name"]: f["fk"] for f in models["Post"]["fields"]}["user_id"] == "users.id"


def test_db_query_is_read_only(client, project_id, sample_project):
    url = f"/api/projects/{project_id}/db/query"
    res = client.post(url, json={"path": "data.db", "sql": "SELECT name FROM users ORDER BY id"}).get_json()
    assert res["rows"] == [["Ann"], ["Bob"]]
    res = client.post(url, json={"path": "data.db", "sql": "DELETE FROM users"})
    assert res.status_code == 400
    res = client.post(url, json={"path": "data.db", "sql": "SELECT name FROM users"}).get_json()
    assert len(res["rows"]) == 2


def test_orm_models_django_and_sqlalchemy2(tmp_path):
    (tmp_path / "models.py").write_text(
        "from django.db import models\n"
        "from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase\n"
        "from pydantic import BaseModel, Field\n\n"
        "class Author(models.Model):\n"
        "    name = models.CharField(max_length=100)\n\n"
        "class Book(models.Model):\n"
        "    author = models.ForeignKey(Author, on_delete=models.CASCADE)\n\n"
        "class Base(DeclarativeBase):\n    pass\n\n"
        "class Team(Base):\n"
        "    __tablename__ = 'teams'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    title: Mapped[str]\n"
        "    members: Mapped[list['Member']] = relationship(back_populates='team')\n\n"
        "class Member(Base):\n"
        "    __tablename__ = 'members'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    team: Mapped['Team']\n\n"
        "class Schema(BaseModel):\n"
        "    name: str = Field(default='x')\n",
        encoding="utf-8",
    )
    models = {m["class"]: m for m in dbschema.orm_models(tmp_path)}
    assert set(models) == {"Author", "Book", "Team", "Member"}
    assert models["Author"]["fields"][0]["type"] == "CharField(max_length=100)"
    assert models["Book"]["fields"][0]["fk"] == "Author"
    team_fields = {f["name"]: f for f in models["Team"]["fields"]}
    assert team_fields["id"]["pk"] and team_fields["title"]["type"] == "str"
    assert models["Team"]["relationships"][0]["name"] == "members"
    assert models["Member"]["relationships"] == [{"name": "team", "target": "'Team'"}]


def test_usage_structure(client, project_id):
    u = client.get(f"/api/projects/{project_id}/usage").get_json()
    assert u["commands"]["install"].endswith("pip install -r requirements.txt")
    assert u["commands"]["run"].endswith("app.py")
    assert "pytest" in u["commands"]["test"]
    assert "app.py" in u["entry_points"]
    assert "flask" in u["dependencies"]["Python"]
    assert u["env_files"][".env.example"] == ["SECRET_KEY", "DATABASE_URL"]
    assert "SECRET_KEY" in u["env_used"]


def test_endpoints_detected(client, project_id):
    eps = client.get(f"/api/projects/{project_id}/endpoints").get_json()["endpoints"]
    found = {(e["path"], tuple(e["methods"]), e["handler"]) for e in eps}
    assert ("/", ("GET",), "index") in found
    assert ("/users/<int:uid>", ("GET", "DELETE"), "user") in found
    assert ("/api/items", ("POST",), "create_item") in found
    assert not any("should-not-be-found" in e["path"] for e in eps)


def test_saved_requests_and_http_proxy(client, project_id):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            payload = json.dumps({"got": json.loads(body), "auth": self.headers.get("Authorization")}).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        client.put(f"/api/projects/{project_id}", json={"api_base_url": base_url})
        res = client.post(f"/api/projects/{project_id}/http", json={
            "method": "POST", "url": "/api/items", "headers": "Authorization: Bearer t", "body": '{"a": 1}',
        }).get_json()
        assert res["status"] == 201
        assert json.loads(res["body"]) == {"got": {"a": 1}, "auth": "Bearer t"}
    finally:
        server.shutdown()

    base = f"/api/projects/{project_id}/requests"
    created = client.post(base, json={"name": "Створити", "method": "post", "url": "/api/items"}).get_json()
    assert created["method"] == "POST"
    client.put(f"{base}/{created['id']}", json={"name": "Створити товар", "method": "POST", "url": "/api/items"})
    assert client.get(base).get_json()["requests"][0]["name"] == "Створити товар"
    client.delete(f"{base}/{created['id']}")
    assert client.get(base).get_json()["requests"] == []


def test_http_proxy_rejects_bad_scheme(client, project_id):
    res = client.post(f"/api/projects/{project_id}/http", json={"url": "file:///etc/passwd"})
    assert res.status_code == 400
