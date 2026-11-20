#!/usr/bin/env python3
"""
TDD Guard — 테스트가 먼저 실패한 증거가 있어야 기능 코드를 고칠 수 있게 한다. (config.json "tdd.enabled" 로 켠다)

  대상(guarded)   config "tdd.paths" 에 맞는 기능 코드 (예: lib/features/**/domain/**). 테스트 · UI · 문서는 대상이 아니다.
  연결된 테스트    대상 파일을 import 하거나 규칙상 짝인 테스트 파일 (팩 import_keys · test_for)
  기록            harness test 가 실행 결과를 .harness/out/tdd.json 에 남긴다 (테스트별 pass · fail · load_error + 파일 내용 해시)

  편집 잠금 해제   연결된 테스트에 RED(fail 또는 load_error) 기록이 있다            → Claude 실행 전 훅이 확인
  완료 조건        연결된 테스트 하나가 behavior RED(fail) → 그 뒤 GREEN(pass) 이고,
                  GREEN 때의 대상 · 테스트 내용이 지금과 같다                       → 종료 전 훅 · verify · pre-commit
  예외            harness tdd skip <파일> --reason …  (사용자 확인 · .harness/tdd-skip.json 커밋 · 파일 내용이 바뀌면 무효)
  재사용 방지      커밋하면 그 파일들의 기록을 지운다 (post-commit) — 다음 변경은 새 RED 가 필요하다
  CI              harness tdd ci --base <ref> — 바뀐 테스트를 변경 전 코드에서 실행해 실패(RED 재현), 변경 후 통과(GREEN) 확인

팩이 제공하는 것: is_test(path) · test_for(src) · import_keys(root, src) · run_tests(root, targets) · prepare(root)
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import HARNESS, OUT, ROOT, git, glob_regex, load_checks, load_config, tracked_files  # noqa: E402

STATE = OUT / "tdd.json"
SKIP = HARNESS / "tdd-skip.json"
RED = {"fail", "load_error"}


# ── 설정 · 팩 ─────────────────────────────────────────────

def settings(cfg):
    t = cfg.get("tdd") or {}
    return bool(t.get("enabled")), [glob_regex(p) for p in t.get("paths", [])], [glob_regex(p) for p in t.get("exclude", [])]


def enabled(cfg):
    return settings(cfg)[0]


def is_guarded(cfg, rel):
    on, paths, exclude = settings(cfg)
    return on and any(p.match(rel) for p in paths) and not any(p.match(rel) for p in exclude)


def impl(cfg, name):
    """프로젝트 검사 모듈 > 팩 검사 모듈 순으로 함수를 찾는다."""
    for m in reversed(load_checks(cfg)):
        if hasattr(m, name):
            return getattr(m, name)
    return None


def is_test(cfg, rel):
    f = impl(cfg, "is_test")
    if f:
        return f(rel)
    return rel.startswith(tuple(cfg.get("test_dirs", [])))


# ── 파일 · 해시 ───────────────────────────────────────────

def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16] if text is not None else None


def content(rel, root=ROOT, staged=False):
    if staged:
        r = subprocess.run(["git", "-C", str(root), "show", f":{rel}"], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else None
    p = root / rel
    return p.read_text(errors="ignore") if p.is_file() else None


def linked_tests(cfg, src, root=ROOT, files=None):
    """대상 src 와 연결된 테스트 파일들 (import 하거나 규칙상 짝)"""
    files = files if files is not None else tracked_files()
    keys = (impl(cfg, "import_keys") or (lambda r, s: [s]))(root, src)
    pair = (impl(cfg, "test_for") or (lambda s: None))(src)
    out = set()
    for t in files:
        if not is_test(cfg, t):
            continue
        if t == pair:
            out.add(t)
            continue
        text = content(t, root) or ""
        if any(k in text for k in keys):
            out.add(t)
    return sorted(out)


# ── 기록 ──────────────────────────────────────────────────

def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"runs": []}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def record_run(cfg, results):
    """harness test 결과 기록: 테스트별 상태 + 그 테스트 · 연결된 대상 파일의 내용 해시"""
    if not enabled(cfg) or not results:
        return
    files = tracked_files()
    guarded = [f for f in files if is_guarded(cfg, f)]
    hashes = {t: digest(content(t)) for t in results}
    for src in guarded:
        if set(linked_tests(cfg, src, files=files)) & set(results):
            hashes[src] = digest(content(src))
    state = load_state()
    state["runs"].append({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "results": results, "hashes": hashes})
    state["runs"] = state["runs"][-200:]
    save_state(state)


def reset(paths):
    state = load_state()
    paths = set(paths)
    for run in state["runs"]:
        run["results"] = {k: v for k, v in run["results"].items() if k not in paths}
        run["hashes"] = {k: v for k, v in run["hashes"].items() if k not in paths}
    state["runs"] = [r for r in state["runs"] if r["results"]]
    save_state(state)


# ── 예외 ──────────────────────────────────────────────────

def load_skips():
    try:
        return json.loads(SKIP.read_text())
    except (OSError, ValueError):
        return {}


def skip_valid(src, text):
    s = load_skips().get(src)
    return bool(s) and s.get("hash") == digest(text)


# ── 판정 ──────────────────────────────────────────────────

def unlocked(cfg, src):
    """(허용 여부, 연결된 테스트, 이유)"""
    if skip_valid(src, content(src)):
        return True, [], "예외(tdd-skip)"
    tests = linked_tests(cfg, src)
    for run in reversed(load_state()["runs"]):
        for t in tests:
            if run["results"].get(t) in RED:
                return True, tests, f"RED 확인: {t} ({run['results'][t]})"
    return False, tests, "RED 미확인"


def cycle(cfg, src, staged=False):
    """(완료 여부, 메시지) — behavior RED → GREEN, GREEN 때 내용 = 지금 내용"""
    now = content(src, staged=staged)
    if skip_valid(src, now):
        return True, "예외(tdd-skip)"
    tests = linked_tests(cfg, src)
    if not tests:
        return False, "연결된 테스트가 없다 — 이 파일을 import 하는 테스트를 먼저 쓴다"
    behavior_red = {t: False for t in tests}
    load_red = stale_green = False
    for run in load_state()["runs"]:
        for t in tests:
            st = run["results"].get(t)
            if st == "fail":
                behavior_red[t] = True
            elif st == "load_error":
                load_red = True
            elif st == "pass" and behavior_red[t]:
                if run["hashes"].get(src) == digest(now) and run["hashes"].get(t) == digest(content(t, staged=staged)):
                    return True, f"RED → GREEN: {t}"
                stale_green = True
    if stale_green:
        return False, "GREEN 이후 코드 · 테스트가 바뀌었다 — harness test 로 다시 통과를 확인한다"
    if any(behavior_red.values()):
        return False, "RED 뒤 GREEN 이 없다 — 구현 후 harness test 로 통과를 확인한다"
    if load_red:
        return False, "컴파일 실패(RED)만 있다 — 골격을 만든 뒤 테스트가 실행돼 실패(behavior RED)하는 것을 확인한다"
    return False, "RED 미확인 — 테스트를 먼저 쓰고 harness test 로 실패를 확인한다"


def check(ctx, mode):
    """check_code.py 에서 호출 — 변경된 대상 파일마다 완료 조건 확인 (CI 는 harness tdd ci 가 한다)"""
    cfg = ctx.cfg
    if not enabled(cfg) or mode == "file" or os.environ.get("GITHUB_ACTIONS") == "true":
        return
    for path in sorted(set(ctx.added) | set(ctx.new)):
        if is_guarded(cfg, path) and (ROOT / path).is_file():
            ok, msg = cycle(cfg, path, staged=(mode == "staged"))
            if not ok:
                ctx.report("tdd", path, 1, msg, ".harness/core/skills/feature/SKILL.md")


# ── CI: RED 재현 ──────────────────────────────────────────

def ci(cfg, base):
    if not enabled(cfg):
        print("TDD Guard 꺼짐 (config.json tdd.enabled)")
        return 0
    run, prepare = impl(cfg, "run_tests"), impl(cfg, "prepare")
    if not run:
        print("팩에 run_tests 가 없어 건너뜀")
        return 0
    base_sha = git("merge-base", base, "HEAD").strip()
    changed = [p for p in git("diff", "--name-only", "--diff-filter=AM", base_sha, "HEAD").split("\n") if p]
    guarded = [p for p in changed if is_guarded(cfg, p)]
    if not guarded:
        print("TDD 대상 변경 없음")
        return 0
    changed_tests = [p for p in changed if is_test(cfg, p)]
    files = tracked_files()
    problems, need = [], {}
    for src in guarded:
        if skip_valid(src, content(src)):
            print(f"  예외: {src} — {load_skips()[src].get('reason')}")
            continue
        tests = sorted(set(linked_tests(cfg, src, files=files)) & set(changed_tests))
        if not tests:
            problems.append((src, "이 변경에 연결된 테스트 변경이 없다 (테스트 먼저 · 또는 harness tdd skip)"))
        else:
            need[src] = tests
    targets = sorted({t for ts in need.values() for t in ts})
    if targets:
        head = run(ROOT, targets)
        tmp = Path(tempfile.mkdtemp())
        wt = tmp / "base"
        try:
            git("worktree", "add", "-q", "--detach", str(wt), base_sha)
            for p in changed:  # 변경 후 테스트 코드(헬퍼 포함)를 변경 전 코드에 얹는다
                if p.startswith(tuple(cfg.get("test_dirs", []))):
                    (wt / p).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(ROOT / p, wt / p)
            if prepare:
                prepare(wt)
            before = run(wt, targets)
        finally:
            subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(wt)], capture_output=True)
            shutil.rmtree(tmp, ignore_errors=True)
        for src, tests in need.items():
            red = [t for t in tests if before.get(t) in RED]
            green = [t for t in tests if head.get(t) == "pass"]
            print(f"  {src}: 변경 전 {', '.join(f'{t}={before.get(t)}' for t in tests)} / 변경 후 {', '.join(f'{t}={head.get(t)}' for t in tests)}")
            if not red:
                problems.append((src, "새 테스트가 변경 전 코드에서도 통과한다 — 바뀐 동작을 고정하지 못했다"))
            elif not green:
                problems.append((src, "변경 후 코드에서 연결된 테스트가 통과하지 않는다"))
    for src, msg in problems:
        print(f"[tdd] {src} — {msg}")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::error file={src},line=1,title=TDD Guard::{msg}")
    if not problems:
        print(f"✓ TDD 증거 확인: 대상 {len(guarded)}개 (RED 재현 → GREEN)")
    return 1 if problems else 0


# ── 명령 ──────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(prog="harness tdd", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("paths", nargs="*")
    s = sub.add_parser("skip")
    s.add_argument("path")
    s.add_argument("--reason", required=True)
    s = sub.add_parser("ci")
    s.add_argument("--base", required=True)
    sub.add_parser("reset-committed")
    a = p.parse_args()
    cfg = load_config()

    if a.cmd == "status":
        if not enabled(cfg):
            print("TDD Guard 꺼짐 (config.json tdd.enabled)")
            return
        paths = a.paths or [f for f in git("diff", "--name-only", "HEAD").split("\n") + git("ls-files", "--others", "--exclude-standard").split("\n") if f]
        for src in (x for x in paths if is_guarded(cfg, x)):
            ok_edit, tests, why = unlocked(cfg, src)
            ok_done, msg = cycle(cfg, src)
            print(f"{src}\n  테스트: {', '.join(tests) or '없음'}\n  편집: {'허용' if ok_edit else '차단'} ({why})\n  완료: {'✓' if ok_done else '✗'} {msg}")
    elif a.cmd == "skip":
        rel = os.path.relpath(Path(a.path).resolve(), ROOT)
        if not is_guarded(cfg, rel):
            sys.exit(f"{rel} 는 TDD 대상이 아니다")
        skips = load_skips()
        skips[rel] = {"reason": a.reason, "hash": digest(content(rel)), "ts": datetime.now(timezone.utc).date().isoformat()}
        SKIP.write_text(json.dumps(dict(sorted(skips.items())), ensure_ascii=False, indent=2) + "\n")
        print(f"✓ 예외 기록: {rel} — {a.reason} (지금 내용에만 유효 · .harness/tdd-skip.json 을 함께 커밋)")
    elif a.cmd == "ci":
        sys.exit(ci(cfg, a.base))
    elif a.cmd == "reset-committed":
        if subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", "HEAD"], capture_output=True).returncode == 0:
            reset([f for f in git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "HEAD").split("\n") if f])


if __name__ == "__main__":
    main()
