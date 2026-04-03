#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
REPO_ROOT = SCRIPT_DIR.parent
PLACEHOLDER_FRAGMENTS = (
    "change-me",
    "replace-me",
    "replace-with",
    "your-",
    "example",
)


@dataclass
class WorkflowState:
    session_id: str
    branch_name: str
    base_branch: str
    prompt: str = ""
    changed_files: list[str] = field(default_factory=list)
    approved: bool = False
    commit_message: str = ""
    commit_sha: str = ""
    pr_url: str = ""
    last_diff_cursor: int = 0
    target_owner: str = ""
    target_repo: str = ""
    updated_at: str = ""


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_config() -> dict[str, str]:
    env_values: dict[str, str] = {}

    for candidate in (
        Path.cwd() / ".env",
        REPO_ROOT / ".env",
        SCRIPT_DIR / ".env",
    ):
        if candidate.exists():
            env_values.update(parse_env_file(candidate))
            break

    for key, value in os.environ.items():
        if value:
            env_values[key] = value

    return env_values


def is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return False
    return any(fragment in lowered for fragment in PLACEHOLDER_FRAGMENTS)


def require_value(config: dict[str, str], key: str) -> str:
    value = config.get(key, "").strip()
    if not value or is_placeholder(value):
        raise SystemExit(f"{key} is missing or still set to a placeholder value.")
    return value


def resolve_workspace(config: dict[str, str]) -> Path:
    configured = config.get("REPO_DEV_WORKSPACE_PATH", "").strip()
    if configured:
        candidate = Path(configured)
        if candidate.exists():
            return candidate.resolve()
    return REPO_ROOT.resolve()


def resolve_state_dir(workspace: Path, config: dict[str, str]) -> Path:
    openfang_home = config.get("OPENFANG_HOME", "").strip()
    if openfang_home:
        root = Path(openfang_home) / "repo-dev"
        root.mkdir(parents=True, exist_ok=True)
        return root
    root = workspace / ".repo-dev-state"
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitize_session_id(session_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", session_id.strip() or "telegram")
    return cleaned.strip("-") or "telegram"


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def state_file_path(state_dir: Path, session_id: str) -> Path:
    return state_dir / f"{sanitize_session_id(session_id)}.json"


def load_state(state_dir: Path, session_id: str) -> WorkflowState | None:
    path = state_file_path(state_dir, session_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return WorkflowState(**payload)


def save_state(state_dir: Path, state: WorkflowState) -> WorkflowState:
    state.updated_at = now_utc()
    state_file_path(state_dir, state.session_id).write_text(
        json.dumps(state.__dict__, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return state


def clear_state(state_dir: Path, session_id: str) -> None:
    path = state_file_path(state_dir, session_id)
    if path.exists():
        path.unlink()


def ensure_safe_directory(workspace: Path) -> None:
    subprocess.run(
        ["git", "config", "--global", "--add", "safe.directory", str(workspace)],
        text=True,
        capture_output=True,
        check=False,
    )


def run_git(workspace: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    ensure_safe_directory(workspace)
    completed = subprocess.run(
        ["git", *args],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise SystemExit(detail or f"git {' '.join(args)} failed with exit code {completed.returncode}")
    return completed


def current_branch(workspace: Path) -> str:
    return run_git(workspace, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def origin_url(workspace: Path) -> str:
    completed = run_git(workspace, "remote", "get-url", "origin", check=False)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def parse_github_repo(url: str) -> tuple[str, str] | tuple[None, None]:
    normalized = url.strip()
    if not normalized:
        return None, None

    https_match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$", normalized)
    if https_match:
        return https_match.group("owner"), https_match.group("repo")

    ssh_match = re.search(r"git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$", normalized)
    if ssh_match:
        return ssh_match.group("owner"), ssh_match.group("repo")

    return None, None


def target_repo(config: dict[str, str], workspace: Path) -> tuple[str | None, str | None]:
    owner = config.get("GITHUB_REPO_OWNER", "").strip()
    repo = config.get("GITHUB_REPO_NAME", "").strip()
    if owner and repo:
        return owner, repo
    return parse_github_repo(origin_url(workspace))


def github_username(config: dict[str, str]) -> str:
    return config.get("GITHUB_USERNAME", "").strip() or "x-access-token"


def git_auth_remote(owner: str, repo: str, username: str, token: str) -> str:
    quoted_user = urllib.parse.quote(username, safe="")
    quoted_token = urllib.parse.quote(token, safe="")
    return f"https://{quoted_user}:{quoted_token}@github.com/{owner}/{repo}.git"


def dirty_files(workspace: Path) -> list[str]:
    output = run_git(workspace, "status", "--porcelain").stdout.splitlines()
    files: list[str] = []
    for line in output:
        if not line:
            continue
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path)
    return files


def changed_files(workspace: Path) -> list[str]:
    tracked = {
        line.strip()
        for line in run_git(workspace, "diff", "--name-only").stdout.splitlines()
        if line.strip()
    }
    untracked = {
        line.strip()
        for line in run_git(workspace, "ls-files", "--others", "--exclude-standard").stdout.splitlines()
        if line.strip()
    }
    return sorted(tracked | untracked)


def patch_for_file(workspace: Path, file_path: str) -> str:
    path_obj = workspace / file_path
    if path_obj.exists() and file_path in {
        line.strip()
        for line in run_git(workspace, "ls-files", "--others", "--exclude-standard").stdout.splitlines()
        if line.strip()
    }:
        completed = run_git(workspace, "diff", "--no-index", "--no-color", "--", os.devnull, file_path, check=False)
        return completed.stdout
    return run_git(workspace, "diff", "--no-color", "--", file_path).stdout


def diff_numstat(workspace: Path) -> tuple[int, int]:
    insertions = 0
    deletions = 0
    for file_path in changed_files(workspace):
        patch = patch_for_file(workspace, file_path)
        for line in patch.splitlines():
            if line.startswith("+++ ") or line.startswith("--- "):
                continue
            if line.startswith("+"):
                insertions += 1
            elif line.startswith("-"):
                deletions += 1
    return insertions, deletions


def ensure_clean_for_new_workflow(workspace: Path) -> None:
    dirty = dirty_files(workspace)
    if dirty:
        raise SystemExit(
            "Workspace is dirty before starting a repo-dev workflow. Clean or reset the repo before repo apply.\n"
            + "\n".join(dirty)
        )


def build_branch_name(config: dict[str, str], session_id: str) -> str:
    prefix = config.get("REPO_DEV_BRANCH_PREFIX", "").strip() or "openfang"
    suffix = sanitize_session_id(session_id)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"{prefix}/{suffix}-{stamp}"


def ensure_branch(workspace: Path, state_dir: Path, config: dict[str, str], session_id: str, prompt: str) -> WorkflowState:
    existing = load_state(state_dir, session_id)
    if existing:
        return existing

    ensure_clean_for_new_workflow(workspace)
    base_branch = config.get("GITHUB_BASE_BRANCH", "").strip() or "main"
    run_git(workspace, "show-ref", "--verify", "--quiet", f"refs/heads/{base_branch}")
    run_git(workspace, "checkout", base_branch)

    branch_name = build_branch_name(config, session_id)
    run_git(workspace, "checkout", "-b", branch_name)

    owner, repo = target_repo(config, workspace)
    state = WorkflowState(
        session_id=session_id,
        branch_name=branch_name,
        base_branch=base_branch,
        prompt=prompt.strip(),
        target_owner=owner or "",
        target_repo=repo or "",
    )
    return save_state(state_dir, state)


def apply_metadata(workspace: Path, state_dir: Path, session_id: str, prompt: str) -> WorkflowState:
    state = load_state(state_dir, session_id)
    if not state:
        raise SystemExit("No active repo-dev workflow for this session. Start with repo apply.")
    state.prompt = prompt.strip() or state.prompt
    state.changed_files = changed_files(workspace)
    return save_state(state_dir, state)


def chunk_diffs(workspace: Path, max_lines: int) -> list[dict[str, Any]]:
    file_chunks: list[dict[str, Any]] = []
    for file_path in changed_files(workspace):
        patch = patch_for_file(workspace, file_path)
        if not patch.strip():
            continue
        lines = patch.rstrip("\n").splitlines()
        if not lines:
            continue
        total = max(1, (len(lines) + max_lines - 1) // max_lines)
        for index, start in enumerate(range(0, len(lines), max_lines), start=1):
            chunk_lines = lines[start : start + max_lines]
            file_chunks.append(
                {
                    "file": file_path,
                    "chunk_index": index,
                    "chunk_total": total,
                    "line_count": len(chunk_lines),
                    "text": "\n".join(chunk_lines),
                }
            )
    return file_chunks


def github_request(
    config: dict[str, str],
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    token = require_value(config, "GITHUB_TOKEN")
    url = f"https://api.github.com{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "openfang-repo-dev",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub API {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"GitHub network error: {exc.reason}") from exc


def github_request_optional(
    config: dict[str, str],
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | None]:
    token = require_value(config, "GITHUB_TOKEN")
    url = f"https://api.github.com{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "openfang-repo-dev",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
            return response.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404:
            return 404, None
        raise SystemExit(f"GitHub API {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"GitHub network error: {exc.reason}") from exc


def ensure_remote_branch(config: dict[str, str], owner: str, repo: str, branch_name: str, base_branch: str) -> None:
    branch_ref = urllib.parse.quote(f"heads/{branch_name}", safe="")
    status, _payload = github_request_optional(config, "GET", f"/repos/{owner}/{repo}/git/ref/{branch_ref}")
    if status == 200:
        return

    base_ref = urllib.parse.quote(f"heads/{base_branch}", safe="")
    base_payload = github_request(config, "GET", f"/repos/{owner}/{repo}/git/ref/{base_ref}")
    base_sha = base_payload["object"]["sha"]
    github_request(
        config,
        "POST",
        f"/repos/{owner}/{repo}/git/refs",
        {
            "ref": f"refs/heads/{branch_name}",
            "sha": base_sha,
        },
    )


def remote_file_sha(config: dict[str, str], owner: str, repo: str, branch_name: str, file_path: str) -> str | None:
    quoted_path = "/".join(urllib.parse.quote(part, safe="") for part in file_path.split("/"))
    status, payload = github_request_optional(
        config,
        "GET",
        f"/repos/{owner}/{repo}/contents/{quoted_path}?ref={urllib.parse.quote(branch_name, safe='')}",
    )
    if status == 404 or payload is None:
        return None
    return str(payload.get("sha", "") or "") or None


def api_push_contents(
    workspace: Path,
    config: dict[str, str],
    state: WorkflowState,
    owner: str,
    repo: str,
) -> dict[str, Any]:
    ensure_remote_branch(config, owner, repo, state.branch_name, state.base_branch)

    author_name = config.get("REPO_DEV_GIT_AUTHOR_NAME", "").strip() or "OpenFang Bot"
    author_email = config.get("REPO_DEV_GIT_AUTHOR_EMAIL", "").strip() or "openfang-bot@local"
    uploaded: list[str] = []
    deleted: list[str] = []
    changed = state.changed_files or changed_files(workspace)
    for file_path in changed:
        quoted_path = "/".join(urllib.parse.quote(part, safe="") for part in file_path.split("/"))
        existing_sha = remote_file_sha(config, owner, repo, state.branch_name, file_path)
        local_path = workspace / file_path
        if local_path.exists():
            content_bytes = local_path.read_bytes()
            github_request(
                config,
                "PUT",
                f"/repos/{owner}/{repo}/contents/{quoted_path}",
                {
                    "message": state.commit_message or f"Update {file_path}",
                    "content": base64.b64encode(content_bytes).decode("ascii"),
                    "branch": state.branch_name,
                    "sha": existing_sha,
                    "committer": {"name": author_name, "email": author_email},
                    "author": {"name": author_name, "email": author_email},
                },
            )
            uploaded.append(file_path)
        elif existing_sha:
            github_request(
                config,
                "DELETE",
                f"/repos/{owner}/{repo}/contents/{quoted_path}",
                {
                    "message": state.commit_message or f"Delete {file_path}",
                    "branch": state.branch_name,
                    "sha": existing_sha,
                    "committer": {"name": author_name, "email": author_email},
                    "author": {"name": author_name, "email": author_email},
                },
            )
            deleted.append(file_path)
    return {
        "method": "contents_api",
        "uploaded_files": uploaded,
        "deleted_files": deleted,
    }


def command_repo_status(args: argparse.Namespace, config: dict[str, str]) -> dict[str, Any]:
    workspace = resolve_workspace(config)
    state_dir = resolve_state_dir(workspace, config)
    session_state = load_state(state_dir, args.session_id)
    origin = origin_url(workspace)
    origin_owner, origin_repo = parse_github_repo(origin)
    target_owner, target_repo_name = target_repo(config, workspace)
    dirty = dirty_files(workspace)
    return {
        "workspace": str(workspace),
        "current_branch": current_branch(workspace),
        "base_branch": (config.get("GITHUB_BASE_BRANCH", "").strip() or "main"),
        "dirty_files": dirty,
        "dirty_count": len(dirty),
        "session_state": session_state.__dict__ if session_state else None,
        "origin_url": origin,
        "remote_owner": origin_owner,
        "remote_repo": origin_repo,
        "target_owner": target_owner,
        "target_repo": target_repo_name,
        "matches_target_repo": origin_owner == target_owner and origin_repo == target_repo_name,
    }


def command_github_preflight(args: argparse.Namespace, config: dict[str, str]) -> dict[str, Any]:
    workspace = resolve_workspace(config)
    owner, repo = target_repo(config, workspace)
    result: dict[str, Any] = {
        "token_present": bool(config.get("GITHUB_TOKEN", "").strip() and not is_placeholder(config.get("GITHUB_TOKEN", ""))),
        "github_username": config.get("GITHUB_USERNAME", "").strip(),
        "target_owner": owner,
        "target_repo": repo,
        "base_branch": config.get("GITHUB_BASE_BRANCH", "").strip() or "main",
        "repo_exists": False,
        "repo_empty": None,
        "default_branch": None,
        "permissions": {},
        "write_probe": {"ok": False, "status": "not-run"},
    }
    if not owner or not repo:
        result["error"] = "GITHUB_REPO_OWNER and GITHUB_REPO_NAME are not fully configured."
        return result
    if not result["token_present"]:
        result["error"] = "GITHUB_TOKEN is not configured."
        return result

    user_payload = github_request(config, "GET", "/user")
    repo_payload = github_request(config, "GET", f"/repos/{owner}/{repo}")
    result["github_user"] = user_payload.get("login")
    result["repo_exists"] = True
    result["repo_empty"] = bool(repo_payload.get("size", 0) == 0 and not repo_payload.get("default_branch"))
    result["default_branch"] = repo_payload.get("default_branch")
    result["private"] = repo_payload.get("private")
    result["permissions"] = repo_payload.get("permissions", {})
    try:
        status, payload = github_request_optional(
            config,
            "POST",
            f"/repos/{owner}/{repo}/git/blobs",
            {
                "content": "openfang-repo-dev-write-probe",
                "encoding": "utf-8",
            },
        )
        if status == 201:
            result["write_probe"] = {"ok": True, "status": "created", "sha": payload.get("sha") if payload else None}
        else:
            result["write_probe"] = {"ok": False, "status": "blocked"}
    except SystemExit as exc:
        result["write_probe"] = {"ok": False, "status": "blocked", "detail": str(exc)}
    return result


def command_ensure_branch(args: argparse.Namespace, config: dict[str, str]) -> dict[str, Any]:
    workspace = resolve_workspace(config)
    state_dir = resolve_state_dir(workspace, config)
    state = ensure_branch(workspace, state_dir, config, args.session_id, args.prompt or "")
    return state.__dict__


def command_apply_metadata(args: argparse.Namespace, config: dict[str, str]) -> dict[str, Any]:
    workspace = resolve_workspace(config)
    state_dir = resolve_state_dir(workspace, config)
    state = apply_metadata(workspace, state_dir, args.session_id, args.prompt or "")
    return state.__dict__


def command_diff_summary(args: argparse.Namespace, config: dict[str, str]) -> dict[str, Any]:
    workspace = resolve_workspace(config)
    state_dir = resolve_state_dir(workspace, config)
    state = load_state(state_dir, args.session_id)
    files = changed_files(workspace)
    insertions, deletions = diff_numstat(workspace)
    return {
        "branch_name": current_branch(workspace),
        "changed_files": files,
        "changed_file_count": len(files),
        "insertions": insertions,
        "deletions": deletions,
        "session_state": state.__dict__ if state else None,
    }


def command_diff_chunks(args: argparse.Namespace, config: dict[str, str]) -> dict[str, Any]:
    workspace = resolve_workspace(config)
    state_dir = resolve_state_dir(workspace, config)
    state = load_state(state_dir, args.session_id)
    max_lines = args.max_lines or int(config.get("REPO_DEV_MAX_DIFF_LINES", "150") or "150")
    cursor = max(args.cursor, 0)
    batch_size = max(args.batch_size, 1)
    chunks = chunk_diffs(workspace, max_lines)
    window = chunks[cursor : cursor + batch_size]
    next_cursor = cursor + len(window)
    if state:
        state.last_diff_cursor = next_cursor
        save_state(state_dir, state)
    return {
        "cursor": cursor,
        "next_cursor": next_cursor,
        "has_more": next_cursor < len(chunks),
        "total_chunks": len(chunks),
        "chunks": window,
    }


def command_commit(args: argparse.Namespace, config: dict[str, str]) -> dict[str, Any]:
    workspace = resolve_workspace(config)
    state_dir = resolve_state_dir(workspace, config)
    state = load_state(state_dir, args.session_id)
    if not state:
        raise SystemExit("No active repo-dev workflow for this session. Nothing to commit.")
    if current_branch(workspace) != state.branch_name:
        run_git(workspace, "checkout", state.branch_name)
    if not dirty_files(workspace):
        raise SystemExit("No working tree changes to commit.")
    changed_before_commit = changed_files(workspace)

    run_git(workspace, "add", "--all")
    author_name = config.get("REPO_DEV_GIT_AUTHOR_NAME", "").strip() or "OpenFang Bot"
    author_email = config.get("REPO_DEV_GIT_AUTHOR_EMAIL", "").strip() or "openfang-bot@local"
    run_git(
        workspace,
        "-c",
        f"user.name={author_name}",
        "-c",
        f"user.email={author_email}",
        "commit",
        "-m",
        args.message,
    )
    commit_sha = run_git(workspace, "rev-parse", "HEAD").stdout.strip()
    state.commit_message = args.message
    state.commit_sha = commit_sha
    state.approved = True
    state.changed_files = changed_before_commit or state.changed_files
    save_state(state_dir, state)
    return {
        "branch_name": state.branch_name,
        "commit_message": state.commit_message,
        "commit_sha": state.commit_sha,
    }


def command_push(args: argparse.Namespace, config: dict[str, str]) -> dict[str, Any]:
    workspace = resolve_workspace(config)
    state_dir = resolve_state_dir(workspace, config)
    state = load_state(state_dir, args.session_id)
    if not state:
        raise SystemExit("No active repo-dev workflow for this session. Nothing to push.")
    owner = state.target_owner or target_repo(config, workspace)[0]
    repo = state.target_repo or target_repo(config, workspace)[1]
    if not owner or not repo:
        raise SystemExit("GitHub target repo is not configured.")
    token = require_value(config, "GITHUB_TOKEN")
    attempted_users: list[str] = []
    push_errors: list[str] = []
    for username in [github_username(config), "x-access-token"]:
        if username in attempted_users:
            continue
        attempted_users.append(username)
        remote = git_auth_remote(owner, repo, username, token)
        completed = run_git(
            workspace,
            "push",
            "--set-upstream",
            remote,
            f"{state.branch_name}:{state.branch_name}",
            check=False,
        )
        if completed.returncode == 0:
            return {
                "branch_name": state.branch_name,
                "target_owner": owner,
                "target_repo": repo,
                "remote_url": f"https://github.com/{owner}/{repo}.git",
                "method": "git",
                "username": username,
            }
        detail = (completed.stderr or completed.stdout or "").strip()
        push_errors.append(f"{username}: {detail}")

    fallback = api_push_contents(workspace, config, state, owner, repo)
    return {
        "branch_name": state.branch_name,
        "target_owner": owner,
        "target_repo": repo,
        "remote_url": f"https://github.com/{owner}/{repo}.git",
        "git_push_errors": push_errors,
        **fallback,
    }


def command_create_draft_pr(args: argparse.Namespace, config: dict[str, str]) -> dict[str, Any]:
    workspace = resolve_workspace(config)
    state_dir = resolve_state_dir(workspace, config)
    state = load_state(state_dir, args.session_id)
    if not state:
        raise SystemExit("No active repo-dev workflow for this session. Nothing to submit.")
    owner = state.target_owner or target_repo(config, workspace)[0]
    repo = state.target_repo or target_repo(config, workspace)[1]
    if not owner or not repo:
        raise SystemExit("GitHub target repo is not configured.")

    title = (args.title or state.commit_message or "Repo-dev update").strip()
    changed = state.changed_files or changed_files(workspace)
    body_lines = [
        "Generated via the OpenFang repo-dev workflow.",
        "",
        "Original prompt:",
        state.prompt or "(not recorded)",
        "",
        "Changed files:",
    ]
    if changed:
        body_lines.extend(f"- {item}" for item in changed)
    else:
        body_lines.append("- No files recorded")
    body = "\n".join(body_lines)

    payload = github_request(
        config,
        "POST",
        f"/repos/{owner}/{repo}/pulls",
        {
            "title": title,
            "head": f"{owner}:{state.branch_name}",
            "base": state.base_branch,
            "body": body,
            "draft": True,
        },
    )
    state.pr_url = payload.get("html_url", "")
    save_state(state_dir, state)
    return {
        "pr_url": state.pr_url,
        "number": payload.get("number"),
        "branch_name": state.branch_name,
        "target_owner": owner,
        "target_repo": repo,
    }


def command_reset_workflow(args: argparse.Namespace, config: dict[str, str]) -> dict[str, Any]:
    workspace = resolve_workspace(config)
    state_dir = resolve_state_dir(workspace, config)
    state = load_state(state_dir, args.session_id)
    if not state:
        return {"reset": False, "reason": "No active repo-dev workflow for this session."}

    if current_branch(workspace) == state.branch_name:
        run_git(workspace, "reset", "--hard", "HEAD")
        run_git(workspace, "clean", "-fd")
        run_git(workspace, "checkout", state.base_branch)

    branch_exists = run_git(workspace, "show-ref", "--verify", "--quiet", f"refs/heads/{state.branch_name}", check=False)
    if branch_exists.returncode == 0:
        run_git(workspace, "branch", "-D", state.branch_name)

    clear_state(state_dir, args.session_id)
    return {"reset": True, "branch_name": state.branch_name}


def add_common_session_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--session-id", default="telegram")
    parser.add_argument("--pretty", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repo workflow helper for OpenFang repo-dev flows")
    subparsers = parser.add_subparsers(dest="command", required=True)

    repo_status = subparsers.add_parser("repo-status")
    add_common_session_arg(repo_status)

    preflight = subparsers.add_parser("github-preflight")
    add_common_session_arg(preflight)

    ensure = subparsers.add_parser("ensure-branch")
    add_common_session_arg(ensure)
    ensure.add_argument("--prompt", default="")

    metadata = subparsers.add_parser("apply-metadata")
    add_common_session_arg(metadata)
    metadata.add_argument("--prompt", default="")

    diff_summary = subparsers.add_parser("diff-summary")
    add_common_session_arg(diff_summary)

    diff_chunks = subparsers.add_parser("diff-chunks")
    add_common_session_arg(diff_chunks)
    diff_chunks.add_argument("--cursor", type=int, default=0)
    diff_chunks.add_argument("--batch-size", type=int, default=1)
    diff_chunks.add_argument("--max-lines", type=int, default=0)

    commit = subparsers.add_parser("commit")
    add_common_session_arg(commit)
    commit.add_argument("--message", required=True)

    push = subparsers.add_parser("push")
    add_common_session_arg(push)

    create_pr = subparsers.add_parser("create-draft-pr")
    add_common_session_arg(create_pr)
    create_pr.add_argument("--title", default="")

    reset = subparsers.add_parser("reset-workflow")
    add_common_session_arg(reset)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config()

    handlers = {
        "repo-status": command_repo_status,
        "github-preflight": command_github_preflight,
        "ensure-branch": command_ensure_branch,
        "apply-metadata": command_apply_metadata,
        "diff-summary": command_diff_summary,
        "diff-chunks": command_diff_chunks,
        "commit": command_commit,
        "push": command_push,
        "create-draft-pr": command_create_draft_pr,
        "reset-workflow": command_reset_workflow,
    }

    result = handlers[args.command](args, config)
    if getattr(args, "pretty", False):
        print(json.dumps(result, indent=2, sort_keys=False))
    else:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
