#!/usr/bin/env python3
"""
Mutation Guard — planner · reviewer 서브에이전트가 허용 범위 밖을 바꾸지 못하게 한다. (config "guard.enabled", 기본 켬)

두 등급 — 보장 수준이 다르다
  [사후 검출 · 보장]   SubagentStart 때 snapshot(HEAD · index · 바뀐/새 파일의 내용 해시) → SubagentStop 때 다시 비교.
                       git 이 볼 수 있는 모든 추적 파일 · 무시되지 않은 새 파일 · 커밋 · stage 를 본다 (셸로 쓴 것 포함).
                       위반이면 그 단계(리뷰 라운드 · 계획)를 무효로 기록하고 메인에게 알린다. 되돌리지 않는다.
  [사전 차단 · 최선]   서브에이전트 안의 파일 편집 도구(Edit · Write · MultiEdit · NotebookEdit)와 git 쓰기 명령을 실행 전에 막는다.
                       셸 리디렉션 · 스크립트로 쓰는 것은 못 막는다 → 사후 검출이 잡는다.
  보지 못하는 것       gitignore 된 파일(빌드 산출물 · 캐시) · 저장소 밖 · .harness/_workspace · .harness/out

허용 범위
  planner   작업 공간(.harness/_workspace) 만
  reviewer  작업 공간 + 테스트 폴더(config test_dirs)의 **새 파일** 만. 기존 테스트 수정 · 삭제는 위반 (약화 금지)
기존 변경(호출 전 dirty · staged)은 baseline 이라 허용한다. 같은 시간에 메인이 도구로 고친 파일은 위반에서 뺀다.
"""
import json
import re
import shlex
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import LOCAL_DIRS, ROOT, file_states, git, has_head  # noqa: E402

ROLES = ("planner", "reviewer")
GIT_WRITE = re.compile(r"\bgit\s+(commit|add|rm|mv|reset|restore|checkout|switch|stash|merge|rebase|cherry-pick|revert|apply|am|push|tag|branch\s+-[dDmM])\b")


def enabled(cfg):
    return bool((cfg.get("guard") or {}).get("enabled", True))


def _dir():
    import work
    d = work.ws() / "guard"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_tree():
    return git("write-tree", check=False).strip()


def snapshot():
    return {"head": git("rev-parse", "HEAD", check=False).strip() if has_head() else "", "index": _index_tree(), "files": file_states()}


def _tracked_at_head(rel):
    import subprocess
    return has_head() and subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"HEAD:{rel}"], capture_output=True).returncode == 0


def _is_test(cfg, rel):
    import tdd
    return tdd.is_test(cfg, rel) or rel.startswith(tuple(cfg.get("test_dirs", [])))


# ── 시작 · 종료 (SubagentStart · SubagentStop) ─────────────

def start(cfg, agent_id, role, session=None):
    if not enabled(cfg) or role not in ROLES:
        return
    import work
    work.ensure("claude-agent", session)
    rec = {"agent_id": agent_id, "role": role, "started_ts": time.time(), "before": snapshot(), "main_touched": [], "done": False}
    (_dir() / f"{agent_id}.json").write_text(json.dumps(rec, ensure_ascii=False))


def note_main_write(rel):
    """메인 에이전트가 도구로 파일을 고쳤다 — 진행 중인 서브에이전트의 위반에서 뺀다."""
    import work
    if work.load() is None:
        return
    for f in _dir().glob("*.json"):
        rec = json.loads(f.read_text())
        if not rec.get("done") and rel not in rec["main_touched"]:
            rec["main_touched"].append(rel)
            f.write_text(json.dumps(rec, ensure_ascii=False))


def violations(cfg, role, before, after, main_touched):
    out = []
    if before["head"] != after["head"]:
        out.append("커밋 · 브랜치를 바꿨다 (HEAD 변경)")
    if before["index"] != after["index"]:
        out.append("stage(index)를 바꿨다")
    b, a = before["files"], after["files"]
    for rel in sorted(set(b) | set(a)):
        if b.get(rel) == a.get(rel) or rel in main_touched or rel.startswith(LOCAL_DIRS):
            continue
        new_file = rel not in b and a.get(rel) not in (None, "deleted") and not _tracked_at_head(rel)
        if role == "reviewer" and new_file and _is_test(cfg, rel):
            continue  # 독립 테스트 작성 허용
        if role == "reviewer" and _is_test(cfg, rel):
            out.append(f"기존 테스트를 고치거나 지웠다: {rel}")
        else:
            out.append(f"허용 범위 밖 변경: {rel}")
    return out


def stop(cfg, agent_id):
    """(역할, 위반 목록) — 기록이 없으면 (None, [])"""
    f = _dir() / f"{agent_id}.json"
    if not f.exists():
        return None, []
    rec = json.loads(f.read_text())
    found = violations(cfg, rec["role"], rec["before"], snapshot(), set(rec["main_touched"]))
    rec.update(done=True, stopped_ts=time.time(), violations=found, reported=False)
    rec.pop("before", None)  # 원문 대신 결과만 남긴다
    f.write_text(json.dumps(rec, ensure_ascii=False))
    if found:
        import events
        import work
        events.record("violation", source="claude-guard", reason=f"{rec['role']}: " + "; ".join(found[:3]))
        state = work.load()
        if state:
            if rec["role"] == "reviewer" and state["rounds"]:
                state["rounds"][-1]["invalid"] = "; ".join(found)
            if rec["role"] == "planner":
                state["planner_invalid"] = "; ".join(found)
            work.save(state)
    return rec["role"], found


def take_unreported():
    """메인에게 아직 알리지 않은 위반 → 메시지 (알린 것으로 표시)"""
    import work
    if work.load() is None:
        return None
    msgs = []
    for f in sorted(_dir().glob("*.json")):
        rec = json.loads(f.read_text())
        if rec.get("done") and rec.get("violations") and not rec.get("reported"):
            msgs.append(f"{rec['role']}({rec['agent_id'][:8]}): " + "; ".join(rec["violations"]))
            rec["reported"] = True
            f.write_text(json.dumps(rec, ensure_ascii=False))
    if not msgs:
        return None
    return ("[하네스 Mutation Guard · 사후 검출] 역할 위반 — 이 단계의 결과는 무효다. 결과를 쓰지 말고, 바뀐 파일을 되돌리지도 말고, "
            "아래 내용을 사용자에게 그대로 보고해 결정을 받는다.\n  " + "\n  ".join(msgs))


# ── 사전 차단 (서브에이전트 안의 PreToolUse) ───────────────

def realtime(cfg, role, tool, tool_input):
    """deny 이유 또는 None — 최선 노력 (도구 · git 명령만)"""
    if not enabled(cfg) or role not in ROLES:
        return None
    if tool == "Bash":
        cmd = tool_input.get("command", "")
        for seg in re.split(r"[;&|]+", cmd):
            if GIT_WRITE.search(seg):
                return f"[Mutation Guard · 사전 차단] {role} 는 git 상태를 바꾸지 않는다: {shlex.quote(seg.strip())[:80]}"
        return None
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    try:
        rel = Path(path).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return f"[Mutation Guard · 사전 차단] {role} 는 저장소 밖 파일을 쓰지 않는다"
    if rel.startswith(".harness/_workspace/"):
        return None
    if role == "reviewer" and _is_test(cfg, rel):
        if (ROOT / rel).exists():
            return f"[Mutation Guard · 사전 차단] reviewer 는 기존 테스트를 고치지 않는다 (약화 금지): {rel} — 새 테스트 파일을 만든다"
        return None
    return f"[Mutation Guard · 사전 차단] {role} 의 허용 범위 밖: {rel} (" + \
        ("작업 공간만" if role == "planner" else "작업 공간 + 새 테스트 파일만") + ")"
