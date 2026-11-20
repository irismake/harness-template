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
from lib import load_config  # noqa: E402


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
    tool_input = data.get("tool_input") or {}
    cfg = load_config()
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
    elif tool in {"Edit", "Write", "MultiEdit", "NotebookEdit"}:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        for pattern in rules.get("file_allow", []):
            if re.search(pattern, path):
                sys.exit(0)
        for pattern, reason in rules.get("file_deny", []):
            if re.search(pattern, path):
                decide("deny", reason)
        for pattern, reason in rules.get("file_ask", []):
            if re.search(pattern, path):
                decide("ask", reason)
    sys.exit(0)


if __name__ == "__main__":
    main()
