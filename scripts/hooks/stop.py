#!/usr/bin/env python3
"""
Claude Code Stop 훅. 응답을 끝내기 전에 작업 브랜치 변경분 전체를 결정적으로 검사한다 (= harness verify).

  - 위반이 있으면 한 번 막고(decision: block) 이유를 Claude 에게 돌려준다.
  - 같은 응답에서 두 번째는 막지 않는다(stop_hook_active) — 고치지 못한 위반은 사용자에게 보고하게 한다.
  - 테스트 · 빌드는 돌리지 않는다 (느림). TDD 테스트는 스킬이, 전체 테스트 · 빌드는 CI 가 맡는다.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import CONFIG_PATH, CORE, ROOT, load_config  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "HARNESS_SOURCE": "claude-stop"})


def main():
    data = json.load(sys.stdin)
    if data.get("stop_hook_active") or not CONFIG_PATH.exists():
        return
    results = [
        run(str(CORE / "scripts/check_rules.py")),
        run(str(CORE / "scripts/check_code.py"), "--lint"),
    ]
    failed = [r for r in results if r.returncode != 0]
    try:  # 종료 전 검사 = harness verify 와 같다 → 완료 게이트의 증거로 남긴다
        import work
        work.record_verify(load_config(), not failed)
    except Exception:  # noqa: BLE001 — 기록 실패가 응답을 막으면 안 된다
        pass
    if not failed:
        return
    report = "\n".join((r.stdout + r.stderr).strip() for r in failed)
    print(json.dumps({
        "decision": "block",
        "reason": "[하네스] 변경분에 규칙 위반이 있습니다. 고치거나, 고치지 않을 이유를 사용자에게 보고하세요.\n" + report,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
