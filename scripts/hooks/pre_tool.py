#!/usr/bin/env python3
"""
Claude Code PreToolUse 훅. 위험한 명령 · 보호 파일 수정을 막고, 외부에 영향을 주는 동작은 사용자 승인을 요구한다.

  deny : 되돌리기 어렵거나 배포 · 서명 · Secret · 공유 하네스에 닿는 동작
  ask  : push · PR · CI/CD · 하네스 설정 변경 → 사용자 확인 창
  그 외: 통과 (Claude Code 의 일반 권한 설정을 따른다)

패턴 = 코어 기본값(lib.DEFAULTS) + 팩(pack.json) + 프로젝트(.harness/config.json) 의 "protected".
보호 브랜치 = config "protected_branches".
"""
import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import events  # noqa: E402
import tdd  # noqa: E402
import work  # noqa: E402
from lib import LOCAL_DIRS, ROOT, load_config  # noqa: E402

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
AGENT_TOOLS = {"Agent", "Task"}
ROLES = {"planner", "reviewer"}


def decide(decision, reason):
    events.record(decision, source="claude-pre-tool", reason=reason)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": f"[하네스] {reason}",
    }}, ensure_ascii=False))
    sys.exit(0)


def pushes_protected_branch(command, protected):
    """`git push origin main` · `HEAD:main` 처럼 보호 브랜치를 대상으로 하는지."""
    for segment in re.split(r"[;&|]+", command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        if "push" not in tokens or "git" not in tokens:
            continue
        args = [t for t in tokens[tokens.index("push") + 1:] if not t.startswith("-")]
        for ref in args[1:]:  # 첫 인자는 remote
            if ref.split(":")[-1].removeprefix("refs/heads/") in protected:
                return True
    return False


def main():
    data = json.load(sys.stdin)
    tool = data.get("tool_name")
    if tool not in WRITE_TOOLS | AGENT_TOOLS | {"Bash"}:
        sys.exit(0)  # 읽기 도구는 바로 통과
    tool_input = data.get("tool_input") or {}
    cfg = load_config()
    session = data.get("session_id")

    if tool in AGENT_TOOLS:
        role = tool_input.get("subagent_type")
        if role in ROLES:
            ok, msg = work.start_role(cfg, role, session)
            if not ok:
                decide("deny", msg)
        sys.exit(0)
    rules = cfg.get("protected", {})

    if tool == "Bash":
        command = tool_input.get("command", "")
        protected = set(cfg.get("protected_branches", []))
        if pushes_protected_branch(command, protected):
            decide("deny", f"보호 브랜치({' · '.join(sorted(protected))})에 직접 push 하지 않는다 — PR 로만")
        for pattern, reason in rules.get("bash_deny", []):
            if re.search(pattern, command):
                decide("deny", reason)
        for pattern, reason in rules.get("bash_ask", []):
            if re.search(pattern, command):
                decide("ask", reason)
    elif tool in WRITE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        _ensure_work(path, session)
        for pattern in rules.get("file_allow", []):
            if re.search(pattern, path):
                sys.exit(0)
        for pattern, reason in rules.get("file_deny", []):
            if re.search(pattern, path):
                decide("deny", reason)
        for pattern, reason in rules.get("file_ask", []):
            if re.search(pattern, path):
                decide("ask", reason)
        tdd_gate(cfg, path)
    sys.exit(0)


def _ensure_work(path, session):
    """프로젝트 파일을 고치기 시작하면 작업 구간을 자동으로 연다 (에이전트가 따로 부르지 않아도 된다)."""
    try:
        rel = Path(path).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return
    if not rel.startswith((*LOCAL_DIRS, ".harness/core/", ".git/")):
        work.ensure("claude", session)


def tdd_gate(cfg, path):
    """TDD Guard: 연결된 테스트의 RED 기록 없이 대상 기능 코드를 고치지 못하게 한다."""
    if not path or not tdd.enabled(cfg):
        return
    try:
        rel = Path(path).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return
    if not tdd.is_guarded(cfg, rel):
        return
    ok, tests, why = tdd.unlocked(cfg, rel)
    if ok:
        return
    hint = (f"연결된 테스트: {', '.join(tests)} — 실패하는 테스트를 쓰고 `.harness/core/harness test {tests[0]}` 로 RED 를 확인하세요."
            if tests else "이 파일을 import 하는 테스트를 먼저 쓰고 `.harness/core/harness test <테스트>` 로 RED 를 확인하세요.")
    decide("deny", f"[TDD Guard] {rel} 수정 차단 — {why}. {hint} (테스트로 고정할 동작이 없으면 사용자에게 `harness tdd skip` 승인을 요청)")


if __name__ == "__main__":
    main()
