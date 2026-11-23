"""Тести + Git, оновлення з проду, помилки, логи."""
import subprocess

from conftest import git


def test_run_tests_detected_command(client, project_id):
    res = client.post(f"/api/projects/{project_id}/tests/run", json={"command": "", "save": True}).get_json()
    assert "pytest" in res["command"]
    # pytest може бути відсутній у системному python — тоді просто перевіряємо, що запуск зафіксовано
    runs = client.get(f"/api/projects/{project_id}/runs?kind=test").get_json()["runs"]
    assert runs[0]["id"] == res["id"]


def test_run_custom_command_and_failure(client, project_id):
    ok = client.post(f"/api/projects/{project_id}/tests/run", json={"command": "echo '3 passed in 0.1s'"}).get_json()
    assert ok["exit_code"] == 0 and ok["summary"] == {"passed": 3}
    bad = client.post(f"/api/projects/{project_id}/tests/run", json={"command": "echo boom; exit 3"}).get_json()
    assert bad["exit_code"] == 3 and "boom" in bad["output"]
    full = client.get(f"/api/projects/{project_id}/runs/{bad['id']}").get_json()
    assert "boom" in full["output"]


def test_command_timeout(app, sample_project):
    from allprojects.services import runner
    res = runner.run_command("sleep 5", sample_project, timeout=1)
    assert res["timed_out"] and res["duration"] < 4


def test_git_status_diff_commit(client, project_id, sample_project):
    base = f"/api/projects/{project_id}/git"
    st = client.get(f"{base}/status").get_json()
    assert st["is_repo"] and st["clean"] and st["branch"] == "main"

    (sample_project / "app.py").write_text("print('changed')\n")
    (sample_project / "new.txt").write_text("hello\n")
    st = client.get(f"{base}/status").get_json()
    paths = {f["path"]: f for f in st["files"]}
    assert paths["new.txt"]["untracked"] and paths["app.py"]["worktree"] == "M"

    assert "+print('changed')" in client.get(f"{base}/diff?path=app.py").get_json()["diff"]
    assert "+hello" in client.get(f"{base}/diff?path=new.txt").get_json()["diff"]

    assert client.post(f"{base}/commit", json={"message": ""}).status_code == 400
    res = client.post(f"{base}/commit", json={"message": "Зміни із застосунку"}).get_json()
    assert res["status"]["clean"]
    log = client.get(f"{base}/log").get_json()["commits"]
    assert log[0]["subject"] == "Зміни із застосунку"
    show = client.get(f"{base}/show/{log[0]['sha']}").get_json()["diff"]
    assert "new.txt" in show
    assert client.get(f"{base}/show/not-a-sha").status_code == 400
    file_log = client.get(f"{base}/log?path=new.txt").get_json()["commits"]
    assert len(file_log) == 1


def test_git_branches_and_bad_names(client, project_id):
    base = f"/api/projects/{project_id}/git"
    assert client.post(f"{base}/checkout", json={"branch": "feature/x", "create": True}).status_code == 200
    st = client.get(f"{base}/status").get_json()
    assert st["branch"] == "feature/x" and "main" in st["branches"]["local"]
    assert client.post(f"{base}/checkout", json={"branch": "--orphan"}).status_code == 400
    assert client.post(f"{base}/checkout", json={"branch": "a b"}).status_code == 400


def test_git_init(client, tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    (folder / "main.py").write_text("print(1)\n")
    pid = client.post("/api/projects", json={"path": str(folder)}).get_json()["id"]
    assert client.get(f"/api/projects/{pid}/git/status").get_json() == {"is_repo": False}
    assert client.post(f"/api/projects/{pid}/git/init").status_code == 200
    assert client.get(f"/api/projects/{pid}/git/status").get_json()["is_repo"]


def test_prod_update_git(client, project_id, sample_project, tmp_path):
    prod = tmp_path / "prod.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(sample_project), str(prod)], check=True)
    git(sample_project, "remote", "add", "prod", str(prod))
    # На «проді» з'являється новий коміт
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(prod), str(work)], check=True)
    (work / "HOTFIX.md").write_text("fix\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "Hotfix on prod")
    git(work, "push", "-q", "origin", "main")

    client.put(f"/api/projects/{project_id}", json={"prod_mode": "git", "prod_remote": "prod", "prod_branch": "main"})
    run = client.post(f"/api/projects/{project_id}/prod/update").get_json()
    assert run["exit_code"] == 0, run["output"]
    assert (sample_project / "HOTFIX.md").exists()
    runs = client.get(f"/api/projects/{project_id}/runs?kind=prod").get_json()["runs"]
    assert len(runs) == 1


def test_prod_update_command(client, project_id, sample_project):
    client.put(f"/api/projects/{project_id}", json={"prod_mode": "command", "prod_cmd": "echo synced > synced.txt"})
    run = client.post(f"/api/projects/{project_id}/prod/update").get_json()
    assert run["exit_code"] == 0
    assert (sample_project / "synced.txt").read_text().strip() == "synced"


def test_incidents_manual_and_ingest(client, app, project_id):
    base = f"/api/projects/{project_id}/incidents"
    assert client.post(base, json={}).status_code == 400
    manual = client.post(base, json={"title": "Бот впав", "message": "після оновлення"}).get_json()
    assert manual["source"] == "manual"

    key = client.get(f"/api/projects/{project_id}").get_json()["ingest_key"]
    tb = 'Traceback (most recent call last):\n  File "app.py", line 9, in index\nZeroDivisionError: division by zero'
    # ingest працює без CSRF-токена (його викликає сам проект)
    r1 = client.raw.post(f"/api/ingest/{key}", json={"title": "ZeroDivisionError: division by zero", "traceback": tb})
    assert r1.status_code == 201
    r2 = client.raw.post(f"/api/ingest/{key}", json={"traceback": tb})
    assert r2.get_json()["id"] == r1.get_json()["id"] and r2.get_json()["occurrences"] == 2
    assert client.raw.post("/api/ingest/wrong-key", json={"title": "x"}).status_code == 404

    iid = r1.get_json()["id"]
    res = client.put(f"{base}/{iid}", json={"status": "resolved", "notes": "виправлено"}).get_json()
    assert res["status"] == "resolved" and res["resolved_at"]
    assert len(client.get(f"{base}?status=open").get_json()["incidents"]) == 1
    # повторна помилка знову відкриває інцидент
    client.raw.post(f"/api/ingest/{key}", json={"traceback": tb})
    assert len(client.get(f"{base}?status=open").get_json()["incidents"]) == 2
    client.delete(f"{base}/{manual['id']}")
    assert len(client.get(f"{base}?status=all").get_json()["incidents"]) == 1


def test_logs(client, project_id):
    files = client.get(f"/api/projects/{project_id}/logs").get_json()["files"]
    assert [f["path"] for f in files] == ["logs/app.log"]
    log = client.get(f"/api/projects/{project_id}/logs/view?path=logs/app.log").get_json()
    assert log["errors"] >= 2 and log["warnings"] == 1
    [tb] = log["tracebacks"]
    assert tb["title"] == "ZeroDivisionError: division by zero"
    assert client.get(f"/api/projects/{project_id}/logs/view?path=../../etc/passwd").status_code in (400, 404)
