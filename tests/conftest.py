import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from allprojects import create_app

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}

SAMPLE_FILES = {
    "README.md": "# Demo\n\nДемо-проект для тестів.\n\n## Запуск\n\n```\npython app.py\n```\n",
    "requirements.txt": "flask>=3\nsqlalchemy\npytest\n",
    "app.py": (
        "import os\n"
        "from flask import Flask\n\n"
        "app = Flask(__name__)\n"
        "SECRET = os.environ.get('SECRET_KEY')\n\n"
        "@app.route('/')\n"
        "def index():\n"
        "    return 'ok'\n\n"
        "@app.route('/users/<int:uid>', methods=['GET', 'DELETE'])\n"
        "def user(uid):\n"
        "    return str(uid)\n\n"
        "@app.post('/api/items')\n"
        "def create_item():\n"
        "    return {}\n\n"
        "if __name__ == '__main__':\n"
        "    app.run()\n"
    ),
    "models.py": (
        "from sqlalchemy import Column, Integer, String, ForeignKey\n"
        "from sqlalchemy.orm import declarative_base, relationship\n\n"
        "Base = declarative_base()\n\n"
        "class User(Base):\n"
        "    __tablename__ = 'users'\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    name = Column(String(80), nullable=False)\n"
        "    posts = relationship('Post')\n\n"
        "class Post(Base):\n"
        "    __tablename__ = 'posts'\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    user_id = Column(Integer, ForeignKey('users.id'))\n"
    ),
    "db/schema.sql": (
        "-- схема\n"
        "CREATE TABLE IF NOT EXISTS orders (\n"
        "  id SERIAL PRIMARY KEY,\n"
        "  user_id INTEGER NOT NULL REFERENCES users(id),\n"
        "  total NUMERIC(10, 2) DEFAULT 0,\n"
        "  created_at TIMESTAMP\n"
        ");\n"
    ),
    "logs/app.log": (
        "2025-01-01 INFO started\n"
        "2025-01-01 WARNING slow query\n"
        "Traceback (most recent call last):\n"
        '  File "app.py", line 9, in index\n'
        "    1 / 0\n"
        "ZeroDivisionError: division by zero\n"
        "2025-01-01 ERROR request failed\n"
    ),
    "tests/test_ok.py": "def test_ok():\n    assert 1 + 1 == 2\n",
    ".env.example": "SECRET_KEY=change-me\nDATABASE_URL=\n",
    "node_modules/pkg/index.js": "app.get('/should-not-be-found', () => {})\n",
}

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def git(cwd, *args):
    env = {**os.environ, **GIT_ENV}
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def sample_project(tmp_path) -> Path:
    root = tmp_path / "projects" / "demo"
    for rel, content in SAMPLE_FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "logo.png").write_bytes(PNG_1PX)
    conn = sqlite3.connect(root / "data.db")
    conn.executescript(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);"
        "CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), title TEXT);"
        "CREATE INDEX idx_posts_user ON posts(user_id);"
        "INSERT INTO users(name) VALUES ('Ann'), ('Bob');"
    )
    conn.commit()
    conn.close()
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Initial commit")
    return root


@pytest.fixture
def app(tmp_path):
    data_dir = tmp_path / "app-data"
    application = create_app({
        "TESTING": True,
        "DATA_DIR": str(data_dir),
        "DATABASE": str(data_dir / "projects.db"),
        "COMMAND_TIMEOUT": 60,
    })
    return application


@pytest.fixture
def client(app):
    c = app.test_client()
    token = app.config["CSRF_TOKEN"]

    class Client:
        raw = c

        def get(self, url, **kw):
            return c.get(url, **kw)

        def _send(self, method, url, **kw):
            headers = kw.pop("headers", {})
            headers.setdefault("X-CSRF-Token", token)
            return getattr(c, method)(url, headers=headers, **kw)

        def post(self, url, **kw):
            return self._send("post", url, **kw)

        def put(self, url, **kw):
            return self._send("put", url, **kw)

        def delete(self, url, **kw):
            return self._send("delete", url, **kw)

    return Client()


@pytest.fixture
def project_id(client, sample_project):
    res = client.post("/api/projects", json={"path": str(sample_project)})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["id"]
