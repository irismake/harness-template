#!/usr/bin/env python3
"""
Claude Code PostToolUse 훅 (Edit · Write · Bash). 방금 고친 소스 · 테스트 파일 하나를 바로 검사하고, Bash 명령이 RED 없이 TDD 대상을 바꿨는지 본다.
위반이 있으면 exit 2 + stderr 로 Claude 에게 알려 그 자리에서 고치게 한다.

대상: config "source_dirs" · "test_dirs" 아래 파일 중 팩 checks.py 의 `post_edit_match(path)` 가 참인 것
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import CORE, ROOT, load_checks, load_config  # noqa: E402


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") in ("Agent", "Task") and not data.get("agent_id"):
        import guard
        msg = guard.take_unreported()
        if msg:  # 서브에이전트가 돌아온 직후 메인에게 위반을 알린다
            print(json.dumps({"decision": "block", "reason": msg}, ensure_ascii=False))
        return
    if data.get("tool_name") == "Bash":
        import tdd
        bad = tdd.bash_after(load_config(), data.get("tool_use_id"))
        if bad:
            print(f"[하네스] [TDD Guard] Bash 로 TDD 대상 코드를 RED 없이 바꿨다: {', '.join(bad)}\n"
                  "되돌리고 테스트부터 쓴다 — 실패하는 테스트 → `.harness/core/harness test <테스트>` 로 RED → Edit · Write 로 구현. "
                  "이미 통과하는 테스트를 덧붙여 넘기지 않는다.", file=sys.stderr)
            sys.exit(2)
        return
    path = (data.get("tool_input") or {}).get("file_path") or ""
    if not path:
        return
    try:
        rel = Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return
    cfg = load_config()
    dirs = tuple(cfg.get("source_dirs", []) + cfg.get("test_dirs", []))
    if not dirs or not rel.startswith(dirs):
        return
    matchers = [m.post_edit_match for m in load_checks(cfg) if hasattr(m, "post_edit_match")]
    if matchers and not any(f(rel) for f in matchers):
        return
    result = subprocess.run(
        [sys.executable, str(CORE / "scripts/check_code.py"), "--file", rel, "--lint"],
        cwd=ROOT, capture_output=True, text=True, env={**os.environ, "HARNESS_SOURCE": "claude-post-edit"},
    )
    if result.returncode != 0:
        print(f"[하네스] {rel} 검사 결과 — 고친 뒤 계속하세요.\n{result.stdout}{result.stderr}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
