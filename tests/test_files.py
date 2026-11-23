"""Папки, редактор коду, структура проекту, пошук, картинки."""
import io


def test_list_folders_and_traversal(client, project_id):
    res = client.get(f"/api/projects/{project_id}/files").get_json()
    names = [e["name"] for e in res["entries"]]
    assert "app.py" in names and "docs" in names
    assert res["entries"][0]["type"] == "dir"  # папки першими
    node_modules = next(e for e in res["entries"] if e["name"] == "node_modules")
    assert node_modules["ignored"]

    for bad in ("../", "../../etc", "/etc/passwd", "docs/../../.."):
        r = client.get(f"/api/projects/{project_id}/file?path={bad}")
        assert r.status_code in (400, 404), bad
        assert r.status_code == 400 or "etc" not in r.get_data(as_text=True)


def test_edit_file_with_history_and_conflict(client, project_id, sample_project):
    f = client.get(f"/api/projects/{project_id}/file?path=app.py").get_json()
    assert f["language"] == "Python"
    new = f["content"].replace("return 'ok'", "return 'hello'")
    res = client.put(f"/api/projects/{project_id}/file", json={"path": "app.py", "content": new, "mtime": f["mtime"]})
    assert res.status_code == 200
    assert "return 'hello'" in (sample_project / "app.py").read_text()

    # Повторний запис зі старим mtime — конфлікт
    res = client.put(f"/api/projects/{project_id}/file", json={"path": "app.py", "content": "x", "mtime": 1.0})
    assert res.status_code == 409

    changes = client.get(f"/api/projects/{project_id}/changes").get_json()["changes"]
    assert changes[0]["kind"] == "edit" and changes[0]["path"] == "app.py"
    detail = client.get(f"/api/projects/{project_id}/changes/{changes[0]['id']}").get_json()
    assert "+    return 'hello'" in detail["diff"]


def test_crlf_preserved(client, project_id, sample_project):
    (sample_project / "win.txt").write_bytes(b"a\r\nb\r\n")
    f = client.get(f"/api/projects/{project_id}/file?path=win.txt").get_json()
    assert f["content"] == "a\nb\n" and f["newline"] == "\r\n"
    client.put(f"/api/projects/{project_id}/file", json={"path": "win.txt", "content": "a\nb\nc\n"})
    assert (sample_project / "win.txt").read_bytes() == b"a\r\nb\r\nc\r\n"


def test_binary_file_rejected_in_editor(client, project_id):
    res = client.get(f"/api/projects/{project_id}/file?path=data.db")
    assert res.status_code == 415


def test_create_rename_delete(client, project_id, sample_project):
    base = f"/api/projects/{project_id}"
    assert client.post(f"{base}/file", json={"path": "src/util", "type": "dir"}).status_code == 201
    assert client.post(f"{base}/file", json={"path": "src/util/a.py", "content": "x = 1\n"}).status_code == 201
    assert client.post(f"{base}/file", json={"path": "src/util/a.py"}).status_code == 400  # вже існує
    res = client.post(f"{base}/rename", json={"path": "src/util/a.py", "new_path": "src/b.py"})
    assert res.get_json()["path"] == "src/b.py"
    assert (sample_project / "src" / "b.py").read_text() == "x = 1\n"
    assert client.delete(f"{base}/file?path=src").status_code == 200
    assert not (sample_project / "src").exists()
    assert client.delete(f"{base}/file?path=").status_code == 400  # корінь не видаляється
    kinds = [c["kind"] for c in client.get(f"{base}/changes").get_json()["changes"]]
    assert kinds[:4] == ["delete", "rename", "create", "create"]


def test_structure_and_stats(client, project_id):
    stats = client.get(f"/api/projects/{project_id}/stats").get_json()
    langs = {l["language"] for l in stats["languages"]}
    assert "Python" in langs and "SQL" in langs
    assert "README.md" in stats["key_files"]
    assert not any("node_modules" in f["path"] for f in stats["largest"])
    tree = client.get(f"/api/projects/{project_id}/tree").get_json()["tree"]
    nm = next(c for c in tree["children"] if c["name"] == "node_modules")
    assert nm["ignored"] and nm["children"] == []


def test_search(client, project_id):
    res = client.get(f"/api/projects/{project_id}/search?q=FLASK").get_json()
    assert any(m["path"] == "app.py" for m in res["matches"])
    res = client.get(f"/api/projects/{project_id}/search?q=FLASK&case=1").get_json()
    assert res["matches"] == []
    res = client.get(f"/api/projects/{project_id}/search?q=def%20\\w%2B\\(&regex=1&glob=*.py").get_json()
    assert {m["path"] for m in res["matches"]} == {"app.py", "tests/test_ok.py"}
    # node_modules пропускається
    res = client.get(f"/api/projects/{project_id}/search?q=should-not-be-found").get_json()
    assert res["matches"] == []
    assert client.get(f"/api/projects/{project_id}/search?q=(&regex=1").status_code == 400


def test_images_list_raw_and_upload(client, project_id, sample_project):
    imgs = client.get(f"/api/projects/{project_id}/images").get_json()["images"]
    assert [i["path"] for i in imgs] == ["docs/logo.png"]
    raw = client.get(f"/projects/{project_id}/raw?path=docs/logo.png")
    assert raw.status_code == 200 and raw.mimetype == "image/png"
    assert "sandbox" in raw.headers["Content-Security-Policy"]
    assert client.get(f"/projects/{project_id}/raw?path=../../x").status_code == 404

    res = client.post(f"/api/projects/{project_id}/images",
                      data={"file": (io.BytesIO(b"<svg/>"), "Схема бази.svg"), "folder": "docs/images"},
                      content_type="multipart/form-data")
    assert res.status_code == 201
    assert (sample_project / res.get_json()["path"]).exists()
    res = client.post(f"/api/projects/{project_id}/images",
                      data={"file": (io.BytesIO(b"x"), "evil.html")}, content_type="multipart/form-data")
    assert res.status_code == 400
