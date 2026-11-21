#!/usr/bin/env python3
"""
작업 구간 — 역할 산출물 · 리뷰 라운드 · 실행 증거 · 완료 게이트 (사람이 따로 관리할 파일 · 명령 없음)

  .harness/_workspace/<브랜치>/        자기 자신을 gitignore 한다 (프로젝트 .gitignore 를 고치지 않는다)
    run.json        브랜치 · 규모(선언 · 하한) · 하네스 버전 · 시작/활동 시각 · 세션 · 리뷰 라운드
    plan.md         planner 산출물
    review_r<N>.md  reviewer 라운드별 산출물 (N 은 하네스가 발급, 덮어쓰지 않음)
  .harness/out/evidence.json          harness verify · harness test 실행 기록 (트리 해시 포함)

자동 시작   Claude: 첫 코드 편집 · planner/reviewer 호출 (훅) / Codex: 에이전트 환경의 git commit (pre-commit)
라운드      reviewer 호출마다 하네스가 번호를 발급, 4번째는 거부 → 사용자에게 보고
완료 게이트 (git pre-push · harness work end)
            모든 규모: 지금 트리로 harness verify 통과 기록
            L 규모 (또는 리뷰를 한 작업): 최신 리뷰 PASS (보고서 형식) · Mutation Guard 위반 없음 + 리뷰 시작 때 소스 해시 = 지금 소스 해시
                       (리뷰 소스 해시는 하네스(.harness/core)를 뺀다 — 하네스 업데이트만으로 리뷰가 무효가 되지 않는다.
                        verify · 테스트 기록은 하네스까지 포함한 트리 해시라 새 검사 기준으로 다시 통과해야 한다)
                       + 지금 트리로 관련 테스트(바뀐 테스트 · 바뀐 코드와 연결된 테스트) 통과 기록
            규모 하한: planner 를 썼거나 risk_areas 를 건드렸거나 layers 두 곳 이상 → L (선언이 작아도)
자동 종료   게이트 통과 시 사용량 집계 후 작업 공간 삭제. 실패 · 중단이면 남아서 이어서 한다
자동 정리   30일 활동 없음 + 브랜치가 없거나 base 에 머지됨 + 지금 브랜치 아님 + 최근 30일 안에 바뀐 파일 없음 일 때만
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import CORE, OUT, ROOT, WORKSPACE, base_ref, changed_files, fingerprint, git, glob_regex, load_config, tree_entries  # noqa: E402

MAX_ROUNDS = 3
STALE_DAYS = 30
ORDER = {"S": 0, "M": 1, "L": 2}
EVIDENCE = OUT / "evidence.json"
VERDICT_RE = re.compile(r"판정:\s*(PASS|FIX_REQUIRED)")
COUNTS_RE = re.compile(r"BLOCKER\s*(\d+)\s*·\s*MAJOR\s*(\d+)\s*·\s*MINOR\s*(\d+)")
UNVERIFIED_RE = re.compile(r"미검증\(필수\)\s*(\d+)")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def harness_version():
    f = CORE / "VERSION"
    return f.read_text().strip() if f.exists() else "개발 중(main)"


def is_agent_env():
    """에이전트가 실행한 명령인지 (사람이 터미널에서 한 커밋 · push 는 작업 기록 · 게이트 대상이 아니다)"""
    env = os.environ
    return bool(env.get("HARNESS_AGENT") or env.get("CLAUDECODE") or any(k.startswith("CODEX_") for k in env))


def branch():
    b = git("rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
    if not b or b == "HEAD":
        b = git("symbolic-ref", "--short", "HEAD", check=False).strip() or "detached-" + git("rev-parse", "--short", "HEAD", check=False).strip()
    return b


def slug(name=None):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name or branch()).strip("-") or "work"


def ws(name=None):
    return WORKSPACE / slug(name)


def load(name=None):
    try:
        return json.loads((ws(name) / "run.json").read_text())
    except (OSError, ValueError):
        return None


def save(state):
    d = WORKSPACE / state["slug"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.json").write_text(json.dumps(state, ensure_ascii=False, indent=1))


def _self_ignore():
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    gi = WORKSPACE / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n")
    OUT.mkdir(parents=True, exist_ok=True)
    if not (OUT / ".gitignore").exists():
        (OUT / ".gitignore").write_text("*\n")


def ensure(source, session=None):
    """작업이 없으면 만들고, 있으면 활동 시각 · 세션을 갱신한다."""
    _self_ignore()
    state = load()
    if state is None:
        cleanup_stale()
        state = {"slug": slug(), "branch": branch(), "lane": None, "started_at": now(), "started_ts": time.time(),
                 "started_by": source, "harness_version": harness_version(), "sessions": [], "rounds": [], "planner": 0}
    state["updated_at"] = now()
    state["updated_ts"] = time.time()
    if session and session not in state["sessions"]:
        state["sessions"].append(session)
    save(state)
    return state


# ── 규모 ──────────────────────────────────────────────────

def lane_floor(cfg, state, changed):
    if state.get("planner"):
        return "L", "planner 를 썼다"
    risk = [glob_regex(p) for p in cfg.get("risk_areas", [])]
    hit = next((f for f in changed if any(r.match(f) for r in risk)), None)
    if hit:
        return "L", f"위험 영역 변경: {hit}"
    layers = [glob_regex(l["files"]) for l in cfg.get("layers", []) if l.get("files")]
    touched = {i for f in changed for i, r in enumerate(layers) if r.match(f)}
    if len(touched) >= 2:
        return "L", "계층 두 곳 이상 변경"
    return "S", "하한 없음"


def effective_lane(cfg, state, changed):
    floor, why = lane_floor(cfg, state, changed)
    declared = state.get("lane") or "S"
    lane = max(declared, floor, key=ORDER.get)
    return lane, why


# ── 실행 증거 ─────────────────────────────────────────────

def _is_test(cfg, rel):
    import tdd
    return tdd.is_test(cfg, rel)


def _is_harness(rel):
    return rel == ".harness/core" or rel.startswith(".harness/core/")


def fingerprints(cfg):
    entries = tree_entries()
    return fingerprint(entries), fingerprint(entries, lambda p: not _is_test(cfg, p))


def review_fingerprint(cfg):
    """리뷰 대상 소스 해시 — 테스트 · 하네스(.harness/core) 제외. 하네스 업데이트는 검사 기준 변경이라 리뷰가 아니라 verify · 테스트로 다시 확인한다."""
    return fingerprint(tree_entries(), lambda p: not _is_test(cfg, p) and not _is_harness(p))


def load_evidence():
    try:
        return json.loads(EVIDENCE.read_text())
    except (OSError, ValueError):
        return {"verify": [], "tests": []}


def _save_evidence(ev):
    _self_ignore()
    ev["verify"] = ev["verify"][-50:]
    ev["tests"] = ev["tests"][-200:]
    EVIDENCE.write_text(json.dumps(ev, ensure_ascii=False, indent=1))


def record_verify(cfg, ok):
    fp_all, fp_src = fingerprints(cfg)
    ev = load_evidence()
    ev["verify"].append({"ts": time.time(), "ok": bool(ok), "fp": fp_all, "fp_src": fp_src})
    _save_evidence(ev)


def record_tests(cfg, results, exit_code=None):
    """results: {테스트 파일: pass|fail|load_error} (구조화 실행기) 또는 None (셸 실행 — exit_code 만)"""
    fp_all, fp_src = fingerprints(cfg)
    ev = load_evidence()
    ev["tests"].append({"ts": time.time(), "fp": fp_all, "fp_src": fp_src, "results": results, "exit": exit_code})
    _save_evidence(ev)


# ── 라운드 ────────────────────────────────────────────────

def start_role(cfg, role, session=None):
    """planner/reviewer 호출 직전 (Claude 실행 전 훅). (허용, 메시지)"""
    state = ensure("claude-agent", session)
    if role == "planner":
        state["planner"] = state.get("planner", 0) + 1
        save(state)
        return True, f"plan: {ws() / 'plan.md'}"
    if role == "reviewer":
        if len(state["rounds"]) >= MAX_ROUNDS:
            return False, (f"리뷰가 이미 {MAX_ROUNDS}라운드다 — 더 고치지 말고 남은 지적 · 시도한 것 · 막힌 이유를 사용자에게 보고한다 "
                           f"(리포트: {', '.join(r['path'] for r in state['rounds'])})")
        _, fp_src = fingerprints(cfg)
        n = len(state["rounds"]) + 1
        path = str((ws() / f"review_r{n}.md").relative_to(ROOT))
        state["rounds"].append({"n": n, "path": path, "started_ts": time.time(), "fp_src": fp_src,
                                "fp_review": review_fingerprint(cfg)})
        save(state)
        return True, f"review round {n}/{MAX_ROUNDS}: {path}"
    return True, ""


def parse_review(path):
    try:
        text = (ROOT / path).read_text()
    except OSError:
        return None
    head = "\n".join(text.splitlines()[:8])
    v, c, u = VERDICT_RE.search(head), COUNTS_RE.search(head), UNVERIFIED_RE.search(head)
    if not (v and c and u):
        return {"error": "보고서 머리줄 형식이 아니다 (판정 · BLOCKER/MAJOR/MINOR · 미검증(필수))"}
    b, m, mi = (int(x) for x in c.groups())
    return {"verdict": v.group(1), "blocker": b, "major": m, "minor": mi, "unverified": int(u.group(1))}


# ── 게이트 ────────────────────────────────────────────────

def required_tests(cfg, changed):
    import tdd
    tests = {f for f in changed if _is_test(cfg, f) and (ROOT / f).is_file()}
    for f in changed:
        if not _is_test(cfg, f) and (ROOT / f).is_file() and f.startswith(tuple(cfg.get("source_dirs", []))):
            tests |= set(tdd.linked_tests(cfg, f))
    return sorted(tests)


def gate(cfg):
    """(문제 목록, 요약) — 작업 기록이 없으면 대상 아님"""
    state = load()
    if state is None:
        return [], "작업 기록 없음 (에이전트 작업이 아님)"
    changed = changed_files(cfg)
    if not changed:
        return [], "바뀐 파일 없음"
    fp_all, fp_src = fingerprints(cfg)
    ev = load_evidence()
    problems = []
    lane, why = effective_lane(cfg, state, changed)

    if not any(v["ok"] and v["fp"] == fp_all for v in ev["verify"]):
        problems.append("지금 코드로 `harness verify` 를 통과한 기록이 없다 — 실행해 통과시킨다")

    if state.get("planner_invalid"):
        problems.append(f"계획 단계가 Mutation Guard 위반으로 무효다 ({state['planner_invalid'][:120]}) — 사용자에게 보고한다")
    if lane == "L" or state["rounds"]:  # 리뷰를 했다면 규모와 관계없이 그 리뷰가 유효해야 한다
        if not state["rounds"]:
            problems.append(f"L 규모({why}) — reviewer 검토가 없다. reviewer 를 호출해 PASS 를 받는다")
        else:
            last = state["rounds"][-1]
            if last.get("invalid"):
                problems.append(f"리뷰(r{last['n']})가 Mutation Guard 위반으로 무효다 ({last['invalid'][:120]}) — 사용자에게 보고하고 다시 리뷰한다")
            rep = parse_review(last["path"])
            if rep is None:
                problems.append(f"리뷰 보고서가 없다: {last['path']}")
            elif "error" in rep:
                problems.append(f"{last['path']}: {rep['error']}")
            else:
                if rep["verdict"] != "PASS":
                    problems.append(f"최신 리뷰(r{last['n']}) 판정이 {rep['verdict']} 다")
                elif rep["blocker"] or rep["major"] or rep["unverified"]:
                    problems.append(f"r{last['n']} 가 PASS 인데 BLOCKER {rep['blocker']} · MAJOR {rep['major']} · 미검증(필수) {rep['unverified']} — PASS 조건이 아니다")
            # 이전 하네스가 연 라운드(fp_review 없음)는 예전 기준(하네스 포함)으로 비교한다
            if ("fp_review" in last and last["fp_review"] != review_fingerprint(cfg)) or \
                    ("fp_review" not in last and last["fp_src"] != fp_src):
                problems.append(f"리뷰(r{last['n']}) 시작 뒤 소스가 바뀌었다 — 바뀐 코드로 다시 리뷰한다")
            runs = [t for t in ev["tests"] if t["fp"] == fp_all]
            shell_ok = any(r.get("results") is None and r.get("exit") == 0 for r in runs)  # 구조화 실행기가 없는 팩
            for t in required_tests(cfg, changed):
                if not shell_ok and not any((r.get("results") or {}).get(t) == "pass" for r in runs):
                    problems.append(f"지금 코드로 통과한 테스트 실행 기록이 없다: {t} (`harness test {t}`)")
    return problems, f"규모 {lane} ({why}) · 라운드 {len(state['rounds'])}/{MAX_ROUNDS}"


def finalize():
    state = load()
    if state is None:
        return
    try:
        import usage  # 사용량 집계 (실패해도 정리는 한다)
        cfg = load_config()
        usage.record_work(state, lane=effective_lane(cfg, state, changed_files(cfg))[0])
    except Exception as e:  # noqa: BLE001 — 측정 실패는 경고만
        if not isinstance(e, ImportError):
            print(f"[usage] warning: {e}", file=sys.stderr)
    shutil.rmtree(ws(), ignore_errors=True)


def cleanup_stale():
    if not WORKSPACE.is_dir():
        return []
    cfg = load_config()
    base = base_ref(cfg)
    current = slug()
    limit = time.time() - STALE_DAYS * 86400
    removed = []
    for d in WORKSPACE.iterdir():
        if not d.is_dir() or d.name == current:
            continue
        try:
            state = json.loads((d / "run.json").read_text())
        except (OSError, ValueError):
            state = {}
        if state.get("updated_ts", 0) > limit:
            continue
        if any(f.stat().st_mtime > limit for f in d.rglob("*") if f.is_file()):
            continue
        b = state.get("branch")
        exists = bool(b) and subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", f"refs/heads/{b}"], capture_output=True).returncode == 0
        merged = exists and base and subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", f"refs/heads/{b}", base], capture_output=True).returncode == 0
        if exists and not merged:
            continue
        shutil.rmtree(d, ignore_errors=True)
        removed.append(d.name)
    return removed


# ── 명령 ──────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(prog="harness work", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("lane")
    s.add_argument("lane", choices=list(ORDER))
    sub.add_parser("current")
    sub.add_parser("gate")
    s = sub.add_parser("pre-push")
    s.add_argument("remote", nargs="?")
    s.add_argument("url", nargs="?")
    sub.add_parser("end")
    sub.add_parser("list")
    sub.add_parser("review-start")   # Codex 등 훅이 없는 도구용 — Claude 는 reviewer 호출 훅이 대신 한다
    sub.add_parser("plan-start")
    s = sub.add_parser("ensure")
    s.add_argument("--source", default="manual")
    a = p.parse_args()
    cfg = load_config()

    if a.cmd == "lane":
        state = ensure("declare")
        state["lane"] = a.lane
        save(state)
        print(f"규모 선언: {a.lane}")
    elif a.cmd == "ensure":
        if is_agent_env() or a.source == "manual":
            ensure(a.source)
    elif a.cmd == "current":
        state = load()
        if not state:
            print("작업 없음 (첫 코드 편집 · planner/reviewer 호출 때 자동으로 시작된다)")
            return
        changed = changed_files(cfg)
        lane, why = effective_lane(cfg, state, changed)
        d = ws().relative_to(ROOT)
        last = state["rounds"][-1]["path"] if state["rounds"] else None
        print(f"작업: {state['slug']} · 규모 {lane} ({why}) · 하네스 {state['harness_version']}")
        print(f"plan: {d}/plan.md")
        print(f"review: {last or '(아직 없음 — reviewer 호출 때 발급)'} · 라운드 {len(state['rounds'])}/{MAX_ROUNDS}")
        print(f"기준: {base_ref(cfg)}")
    elif a.cmd in ("gate", "end", "pre-push"):
        if a.cmd == "pre-push" and not is_agent_env():
            return  # 사람이 직접 하는 push 는 대상 아님
        problems, summary = gate(cfg)
        if problems:
            print(f"[하네스] 작업 완료 조건 미충족 — {summary}")
            for x in problems:
                print(f"  - {x}")
            sys.exit(1)
        print(f"✓ 작업 완료 조건 통과 — {summary}")
        if a.cmd in ("end", "pre-push"):
            finalize()
    elif a.cmd in ("review-start", "plan-start"):
        ok, msg = start_role(cfg, "reviewer" if a.cmd == "review-start" else "planner")
        print(msg)
        if not ok:
            sys.exit(1)
    elif a.cmd == "list":
        for d in sorted(WORKSPACE.glob("*/run.json")) if WORKSPACE.is_dir() else []:
            st = json.loads(d.read_text())
            print(f"{st['slug']}: 시작 {st['started_at']} · 활동 {st.get('updated_at')} · 라운드 {len(st['rounds'])} · 하네스 {st['harness_version']}")


if __name__ == "__main__":
    main()
