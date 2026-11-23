"""Git-операції для вкладок «Тести + Git», «Історія змін» та «Оновлення з проду»."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

MAX_DIFF = 400_000
_REF_RE = re.compile(r"^[A-Za-z0-9._/@+\-]+$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{4,40}$")


class GitError(RuntimeError):
    pass


def _env() -> dict:
    env = os.environ.copy()
    env.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8", "GIT_PAGER": "cat", "GIT_OPTIONAL_LOCKS": "0"})
    return env


def run(root: Path | str, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_env(),
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise GitError("Git не встановлений або не знайдений у PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"Git-команда не завершилась за {timeout} с: git {' '.join(args)}") from exc


def _out(proc: subprocess.CompletedProcess) -> str:
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


def check_ref(name: str, what: str = "гілки") -> str:
    name = (name or "").strip()
    if not name or name.startswith("-") or ".." in name or not _REF_RE.match(name):
        raise GitError(f"Некоректна назва {what}: {name!r}")
    return name


def is_repo(root: Path | str) -> bool:
    try:
        proc = run(root, "rev-parse", "--is-inside-work-tree", timeout=10)
    except GitError:
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _parse_branch_line(line: str) -> dict:
    # "## main...origin/main [ahead 1, behind 2]" або "## No commits yet on main"
    info = {"branch": "", "upstream": "", "ahead": 0, "behind": 0}
    text = line[3:].strip()
    if text.startswith("No commits yet on "):
        info["branch"] = text[len("No commits yet on "):]
        return info
    if text.startswith("HEAD (no branch)"):
        info["branch"] = "(detached HEAD)"
        return info
    m = re.match(r"^(.*?)(?:\.\.\.(\S+))?(?: \[(.*)\])?$", text)
    if m:
        info["branch"] = m.group(1)
        info["upstream"] = m.group(2) or ""
        for part in (m.group(3) or "").split(","):
            part = part.strip()
            if part.startswith("ahead "):
                info["ahead"] = int(part.split()[1])
            elif part.startswith("behind "):
                info["behind"] = int(part.split()[1])
    return info


def status(root: Path | str) -> dict:
    if not is_repo(root):
        return {"is_repo": False}
    proc = run(root, "status", "--porcelain=v1", "-b", "-uall")
    if proc.returncode != 0:
        raise GitError(_out(proc))
    lines = proc.stdout.splitlines()
    info = {"is_repo": True, "files": []}
    if lines and lines[0].startswith("## "):
        info.update(_parse_branch_line(lines[0]))
        lines = lines[1:]
    for line in lines:
        if len(line) < 4:
            continue
        x, y, path = line[0], line[1], line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        info["files"].append({"path": path, "index": x, "worktree": y, "untracked": x == "?"})
    info["clean"] = not info["files"]
    return info


def brief(root: Path | str) -> dict:
    """Коротка інформація для картки проекту на головній."""
    st = status(root)
    if not st.get("is_repo"):
        return {"is_repo": False}
    last = log(root, limit=1)
    return {
        "is_repo": True,
        "branch": st.get("branch", ""),
        "changed": len(st.get("files", [])),
        "ahead": st.get("ahead", 0),
        "behind": st.get("behind", 0),
        "last_commit": last[0] if last else None,
    }


def branches(root: Path | str) -> dict:
    proc = run(root, "for-each-ref", "--format=%(refname)\x1f%(refname:short)\x1f%(HEAD)",
               "refs/heads", "refs/remotes")
    local, remote, current = [], [], ""
    for line in proc.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        full, short, head = parts
        if full.startswith("refs/heads/"):
            local.append(short)
            if head == "*":
                current = short
        elif not full.endswith("/HEAD"):
            remote.append(short)
    if not current:
        cur = run(root, "symbolic-ref", "--short", "-q", "HEAD")
        current = cur.stdout.strip()
    return {"current": current, "local": local, "remote": remote, "remotes": remotes(root)}


def remotes(root: Path | str) -> list[dict]:
    proc = run(root, "remote", "-v")
    seen = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] not in seen:
            seen[parts[0]] = parts[1]
    return [{"name": k, "url": v} for k, v in seen.items()]


def log(root: Path | str, limit: int = 100, path: str | None = None) -> list[dict]:
    args = ["log", f"-n{int(limit)}", "--date=iso-strict",
            "--pretty=format:%H\x1f%h\x1f%an\x1f%ae\x1f%ad\x1f%s\x1e"]
    if path:
        args += ["--", path]
    proc = run(root, *args)
    if proc.returncode != 0:
        return []
    commits = []
    for chunk in proc.stdout.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        parts = chunk.split("\x1f")
        if len(parts) != 6:
            continue
        commits.append({"sha": parts[0], "short": parts[1], "author": parts[2], "email": parts[3],
                        "date": parts[4], "subject": parts[5]})
    return commits


def _cap(text: str) -> str:
    if len(text) > MAX_DIFF:
        return text[:MAX_DIFF] + "\n… (обрізано)"
    return text


def show(root: Path | str, sha: str) -> str:
    if not _SHA_RE.match(sha or ""):
        raise GitError("Некоректний хеш коміту")
    proc = run(root, "show", "--stat", "--patch", "--no-color", "--format=fuller", sha)
    if proc.returncode != 0:
        raise GitError(_out(proc))
    return _cap(proc.stdout)


def diff(root: Path | str, path: str | None = None, staged: bool = False) -> str:
    args = ["diff", "--no-color"]
    if staged:
        args.append("--cached")
    if path:
        args += ["--", path]
    proc = run(root, *args)
    text = proc.stdout
    if path and not text:
        # Новий (невідстежуваний) файл — показуємо як повністю доданий.
        proc2 = run(root, "diff", "--no-color", "--no-index", "--", os.devnull, path)
        text = proc2.stdout
    return _cap(text)


def init(root: Path | str) -> str:
    proc = run(root, "init")
    if proc.returncode != 0:
        raise GitError(_out(proc))
    return _out(proc)


def commit(root: Path | str, message: str, paths: list[str] | None = None) -> str:
    message = (message or "").strip()
    if not message:
        raise GitError("Напишіть повідомлення коміту")
    add_args = ["add", "-A", "--"] + (paths or ["."])
    proc = run(root, *add_args)
    if proc.returncode != 0:
        raise GitError(_out(proc))
    proc = run(root, "commit", "-m", message)
    if proc.returncode != 0:
        out = _out(proc)
        if "Please tell me who you are" in out or "user.email" in out:
            out += ("\n\nНалаштуйте автора:  git config --global user.name \"Ім'я\"  та  "
                    "git config --global user.email \"you@example.com\"")
        raise GitError(out)
    return _out(proc)


def fetch(root: Path | str, remote: str | None = None) -> str:
    args = ["fetch", "--prune"]
    if remote:
        args.append(check_ref(remote, "remote"))
    else:
        args.append("--all")
    proc = run(root, *args, timeout=300)
    if proc.returncode != 0:
        raise GitError(_out(proc))
    return _out(proc) or "Fetch виконано"


def pull(root: Path | str, remote: str | None = None, branch: str | None = None) -> str:
    args = ["pull", "--ff-only"]
    if remote:
        args.append(check_ref(remote, "remote"))
        if branch:
            args.append(check_ref(branch))
    proc = run(root, *args, timeout=300)
    if proc.returncode != 0:
        raise GitError(_out(proc))
    return _out(proc)


def push(root: Path | str, remote: str | None = None, branch: str | None = None) -> str:
    args = ["push"]
    if remote:
        args.append(check_ref(remote, "remote"))
        if branch:
            args.append(check_ref(branch))
    proc = run(root, *args, timeout=300)
    if proc.returncode != 0:
        out = _out(proc)
        if "no upstream branch" in out:
            cur = run(root, "symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
            if cur:
                proc = run(root, "push", "-u", "origin", check_ref(cur), timeout=300)
                if proc.returncode == 0:
                    return _out(proc)
                out = _out(proc)
        raise GitError(out)
    return _out(proc) or "Push виконано"


def checkout(root: Path | str, branch: str, create: bool = False) -> str:
    branch = check_ref(branch)
    args = ["checkout", "-b", branch] if create else ["checkout", branch]
    proc = run(root, *args)
    if proc.returncode != 0:
        raise GitError(_out(proc))
    return _out(proc)
