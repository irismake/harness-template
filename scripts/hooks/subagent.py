#!/usr/bin/env python3
"""
Claude Code SubagentStart · SubagentStop 훅 — Mutation Guard 의 사후 검출 (scripts/guard.py).
  Start: planner · reviewer 의 시작 상태 snapshot (agent_id 별)
  Stop : 다시 비교 → 위반이면 그 단계를 무효로 기록. 메인에게는 Agent 실행 후 훅 · 종료 전 훅이 알린다.
서브에이전트를 막거나 계속 돌리지 않는다 (Stop 에서 block 하면 서브에이전트가 이어서 일하기 때문).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard  # noqa: E402
from lib import CONFIG_PATH, load_config  # noqa: E402


def main():
    data = json.load(sys.stdin)
    if not CONFIG_PATH.exists():
        return
    cfg = load_config()
    agent_id, role = data.get("agent_id"), data.get("agent_type")
    if not agent_id:
        return
    try:
        if data.get("hook_event_name") == "SubagentStart" and role in guard.ROLES:
            guard.start(cfg, agent_id, role, data.get("session_id"))
        elif data.get("hook_event_name") == "SubagentStop":  # 시작 기록이 있는 에이전트만 비교한다
            guard.stop(cfg, agent_id)
    except Exception as e:  # noqa: BLE001 — 훅 실패가 작업을 막으면 안 된다 (경고만)
        print(f"[하네스] Mutation Guard 경고: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
