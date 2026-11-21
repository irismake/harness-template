#!/usr/bin/env python3
"""
토큰 사용량 측정 — 에이전트의 자기 보고가 아니라 로컬 세션 기록을 스크립트로 읽는다. 숫자만 남긴다 (대화 · 코드 원문 없음).

출처
  Claude Code  ~/.claude/projects/<프로젝트>/<세션>.jsonl (메인)  ·  <세션>/subagents/agent-*.jsonl + .meta.json (agentType = 역할)
               응답 하나가 여러 줄로 기록되므로 message.id 로 중복을 없앤다. 줄마다 timestamp · gitBranch 가 있다.
  Codex        ~/.codex/sessions/**/rollout-*.jsonl — session_meta(cwd · git.branch) + token_count(누적값, timestamp)
               서브에이전트 구분이 없어 역할은 main 하나다. 구간 사용량 = 구간 끝 누적 − 구간 시작 누적.

측정 단위
  작업 구간   harness 작업(work) 시작 ~ 완료 게이트 통과 — 역할(main · planner · reviewer) · 규모(S/M/L) · 하네스 버전 · 라운드
              → .harness/out/usage.jsonl 에 한 줄 (gitignore)
  브랜치      작업 기록이 없던 과거도 포함: 세션 기록의 gitBranch 로 묶고, 그 시점 .harness/core 포인터로 하네스 버전을 찾는다
              (.harness/core 가 없던 때 = "도입 전") → 하네스 도입 전후 · 버전 간 실측 비교

토큰 = input(캐시 아님) + cache_write + cache_read + output. 단가 · 비용은 계산하지 않는다 (요금제마다 다름).

사용: harness usage                     작업 구간 · 브랜치 집계 (하네스 버전 × 규모 × 역할)
      harness usage --since 2026-11-01
      harness usage --compare 0.3.0 0.4.0   두 버전의 실측 중앙값 비교 (표본 수와 함께)
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import OUT, ROOT, base_ref, git, load_config  # noqa: E402

USAGE = OUT / "usage.jsonl"
CLAUDE_HOME = Path(os.environ.get("HARNESS_CLAUDE_HOME", Path.home() / ".claude"))
CODEX_HOME = Path(os.environ.get("HARNESS_CODEX_HOME", Path.home() / ".codex"))
KEYS = ("input", "cache_write", "cache_read", "output")


def _ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def _empty():
    return {k: 0 for k in KEYS} | {"messages": 0, "calls": 0}


def _add(acc, u):
    for k in KEYS:
        acc[k] += u.get(k, 0)
    acc["messages"] += u.get("messages", 1)


def total(u):
    return sum(u.get(k, 0) for k in KEYS)


# ── Claude ────────────────────────────────────────────────

def claude_project_dirs(root=ROOT):
    base = CLAUDE_HOME / "projects"
    if not base.is_dir():
        return []
    want = re.sub(r"[^A-Za-z0-9]", "-", str(Path(root).resolve()))
    alt = re.sub(r"[^A-Za-z0-9]", "-", str(root))
    return [d for d in base.iterdir() if d.is_dir() and d.name in (want, alt)]


def _claude_messages(path):
    """jsonl → [(message.id, ts, gitBranch, usage)] — message.id 당 하나 (가장 큰 output 을 쓴다)"""
    best = {}
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if '"assistant"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                m = d.get("message") or {}
                u = m.get("usage") or {}
                mid = m.get("id") or d.get("uuid")
                rec = {"input": u.get("input_tokens", 0) or 0, "cache_write": u.get("cache_creation_input_tokens", 0) or 0,
                       "cache_read": u.get("cache_read_input_tokens", 0) or 0, "output": u.get("output_tokens", 0) or 0}
                prev = best.get(mid)
                if prev is None or rec["output"] >= prev[3]["output"]:
                    best[mid] = (mid, _ts(d.get("timestamp")), d.get("gitBranch"), rec)
    except OSError:
        return []
    return list(best.values())


def claude_sessions(root=ROOT):
    """[{id, main: [msgs], subagents: [{role, msgs}]}]"""
    out = []
    for pdir in claude_project_dirs(root):
        for f in pdir.glob("*.jsonl"):
            sid = f.stem
            subs = []
            sdir = pdir / sid / "subagents"
            if sdir.is_dir():
                for af in sdir.glob("agent-*.jsonl"):
                    try:
                        role = json.loads(af.with_suffix(".meta.json").read_text()).get("agentType") or "other"
                    except (OSError, ValueError):
                        role = "other"
                    subs.append({"role": role, "msgs": _claude_messages(af)})
            out.append({"id": sid, "main": _claude_messages(f), "subagents": subs})
    return out


def claude_window(sessions, start, end, branch=None, session_ids=None):
    roles = defaultdict(_empty)
    for s in sessions:
        if session_ids and s["id"] not in session_ids:
            continue
        for _, ts, br, u in s["main"]:
            if ts and start <= ts <= end and (branch is None or br in (None, branch)):
                _add(roles["main"], u)
        for sub in s["subagents"]:
            msgs = [m for m in sub["msgs"] if m[1] and start <= m[1] <= end]
            if msgs:
                roles[sub["role"]]["calls"] += 1
                for m in msgs:
                    _add(roles[sub["role"]], m[3])
    return dict(roles)


# ── Codex ─────────────────────────────────────────────────

def codex_sessions(root=ROOT):
    base = CODEX_HOME / "sessions"
    if not base.is_dir():
        return []
    rootp = str(Path(root).resolve())
    out = []
    for f in base.rglob("rollout-*.jsonl"):
        meta, points = None, []
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if '"session_meta"' not in line and '"token_count"' not in line:
                        continue
                    d = json.loads(line)
                    p = d.get("payload") or {}
                    if d.get("type") == "session_meta":
                        meta = p
                    elif p.get("type") == "token_count" and (p.get("info") or {}).get("total_token_usage"):
                        points.append((_ts(d.get("timestamp")), p["info"]["total_token_usage"]))
        except (OSError, ValueError):
            continue
        if meta and str(Path(meta.get("cwd", "")).resolve()).startswith(rootp) and points:
            out.append({"id": meta.get("id") or f.stem, "branch": (meta.get("git") or {}).get("branch"), "points": points})
    return out


def _codex_usage(t):
    cached = t.get("cached_input_tokens", 0) or 0
    return {"input": max((t.get("input_tokens", 0) or 0) - cached, 0), "cache_write": t.get("cache_write_input_tokens", 0) or 0,
            "cache_read": cached, "output": t.get("output_tokens", 0) or 0}


def codex_window(sessions, start, end, branch=None):
    acc = _empty()
    for s in sessions:
        if branch and s["branch"] not in (None, branch):
            continue
        before = [u for ts, u in s["points"] if ts and ts < start]
        inside = [u for ts, u in s["points"] if ts and start <= ts <= end]
        if not inside:
            continue
        a, b = _codex_usage(before[-1]) if before else {k: 0 for k in KEYS}, _codex_usage(inside[-1])
        _add(acc, {k: max(b[k] - a[k], 0) for k in KEYS} | {"messages": len(inside)})
    return acc


# ── 작업 구간 기록 (work.finalize 가 부른다) ───────────────

def record_work(state, lane=None, end=None):
    end = end or time.time()
    start = state.get("started_ts") or end
    roles = claude_window(claude_sessions(), start, end, state.get("branch"), set(state.get("sessions") or []) or None)
    codex = codex_window(codex_sessions(), start, end, state.get("branch"))
    agent = "claude" if roles else ("codex" if codex["messages"] else "none")
    if codex["messages"]:
        roles.setdefault("codex-main", codex)
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "work", "slug": state.get("slug"),
           "branch": state.get("branch"), "lane": lane or state.get("lane") or "S", "harness_version": state.get("harness_version"),
           "started_ts": start, "ended_ts": end, "rounds": len(state.get("rounds") or []), "agent": agent, "roles": roles}
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    with open(USAGE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load_works(since=None):
    try:
        rows = [json.loads(l) for l in USAGE.read_text().splitlines() if l.strip()]
    except OSError:
        return []
    return [r for r in rows if not since or r["started_ts"] >= since]


# ── 브랜치 집계 (과거 포함) ───────────────────────────────

_version_cache = {}


def version_for_commit(commit):
    """그 커밋의 .harness/core → 하네스 버전. 없으면 "도입 전", 커밋을 모르면 "?" """
    if not commit:
        return "도입 전"
    if commit in _version_cache:
        return _version_cache[commit]
    if subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True).returncode != 0:
        return "?"
    line = git("ls-tree", commit, ".harness/core", check=False).strip()
    if not line:
        v = "도입 전"
    elif line.split()[1] == "tree":  # 서브모듈이 아니라 파일로 들어 있다
        v = git("show", f"{commit}:.harness/core/VERSION", check=False).strip() or "개발 중(main)"
    else:
        sha = line.split()[2]
        core = str(ROOT / ".harness/core")
        v = subprocess.run(["git", "-C", core, "show", f"{sha}:VERSION"], capture_output=True, text=True).stdout.strip()
        if not v:
            tag = subprocess.run(["git", "-C", core, "describe", "--tags", "--abbrev=0", sha], capture_output=True, text=True).stdout.strip()
            v = tag.lstrip("v") or sha[:7]
    _version_cache[commit] = v
    return v


def harness_version_at(ts):
    """그 시각 base 브랜치의 하네스 버전 (없으면 '도입 전')"""
    base = base_ref(load_config()) or "HEAD"
    when = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # git 은 ISO 만 정확히 읽는다
    return version_for_commit(git("rev-list", "-1", f"--before={when}", base, check=False).strip())


def branch_groups(since=None):
    """{(branch): {first, last, roles}} — Claude 기록의 gitBranch 기준"""
    groups = {}
    for s in claude_sessions():
        for _, ts, br, u in s["main"]:
            if not ts or not br or (since and ts < since):
                continue
            g = groups.setdefault(br, {"first": ts, "last": ts, "roles": defaultdict(_empty)})
            g["first"], g["last"] = min(g["first"], ts), max(g["last"], ts)
            _add(g["roles"]["main"], u)
        # 서브에이전트는 그 세션의 메인 메시지 브랜치 중 가장 가까운 것으로
        for sub in s["subagents"]:
            msgs = [m for m in sub["msgs"] if m[1] and (not since or m[1] >= since)]
            if not msgs:
                continue
            t0 = msgs[0][1]
            near = min((m for m in s["main"] if m[1] and m[2]), key=lambda m: abs(m[1] - t0), default=None)
            if near and near[2] in groups:
                r = groups[near[2]]["roles"][sub["role"]]
                r["calls"] += 1
                for m in msgs:
                    _add(r, m[3])
    for br, g in groups.items():
        g["version"] = harness_version_at(g["first"])
    return groups


# ── 보고 ──────────────────────────────────────────────────

def _med(xs):
    return int(statistics.median(xs)) if xs else 0


def _fmt(n):
    return f"{n/1000:,.1f}K" if n >= 1000 else str(n)


def report(since=None):
    works = load_works(since)
    print(f"## 작업 구간 실측 ({len(works)}건, 출처: .harness/out/usage.jsonl — 작업 시작 ~ 완료 게이트)\n")
    if works:
        print("| 하네스 | 규모 | 작업 | 중앙값 전체 | 중앙값 main | reviewer (호출) | planner (호출) | 라운드 중앙값 |")
        print("|---|---|---|---|---|---|---|---|")
        by = defaultdict(list)
        for w in works:
            by[(w["harness_version"], w["lane"])].append(w)
        for (v, lane), ws in sorted(by.items()):
            tot = [sum(total(r) for r in w["roles"].values()) for w in ws]
            main = [total(w["roles"].get("main") or w["roles"].get("codex-main") or {}) for w in ws]
            rev = [total(w["roles"].get("reviewer", {})) for w in ws]
            pln = [total(w["roles"].get("planner", {})) for w in ws]
            calls_r = sum(w["roles"].get("reviewer", {}).get("calls", 0) for w in ws)
            calls_p = sum(w["roles"].get("planner", {}).get("calls", 0) for w in ws)
            print(f"| {v} | {lane} | {len(ws)} | {_fmt(_med(tot))} | {_fmt(_med(main))} | {_fmt(_med(rev))} ({calls_r}) | {_fmt(_med(pln))} ({calls_p}) | {_med([w['rounds'] for w in ws])} |")
    groups = branch_groups(since)
    print(f"\n## 브랜치 실측 ({len(groups)}개, 출처: Claude 세션 기록 gitBranch — 작업 기록이 없던 과거 포함)\n")
    if groups:
        print("| 하네스 | 브랜치 | 중앙값 전체 | 중앙값 main | 중앙값 서브에이전트 | 메시지 중앙값 |")
        print("|---|---|---|---|---|---|")
        by = defaultdict(list)
        for g in groups.values():
            by[g["version"]].append(g)
        for v, gs in sorted(by.items()):
            tot = [sum(total(r) for r in g["roles"].values()) for g in gs]
            main = [total(g["roles"]["main"]) for g in gs]
            sub = [sum(total(r) for k, r in g["roles"].items() if k != "main") for g in gs]
            print(f"| {v} | {len(gs)} | {_fmt(_med(tot))} | {_fmt(_med(main))} | {_fmt(_med(sub))} | {_med([g['roles']['main']['messages'] for g in gs])} |")
    print("\n토큰 = input + cache_write + cache_read + output (원문 · 비용 없음). 표본이 5개 미만이면 비교에 쓰지 않는다.")


def compare(a, b, since=None):
    works = load_works(since)
    groups = branch_groups(since)
    print(f"## 하네스 {a} → {b} 실측 비교 (중앙값)\n")
    print("| 측정 | 규모 | " + a + " (표본) | " + b + " (표본) | 변화 |")
    print("|---|---|---|---|---|")
    for lane in ("S", "M", "L"):
        for label, f in (("작업 전체", lambda w: sum(total(r) for r in w["roles"].values())),
                         ("작업 main", lambda w: total(w["roles"].get("main") or w["roles"].get("codex-main") or {}))):
            xa = [f(w) for w in works if w["harness_version"] == a and w["lane"] == lane]
            xb = [f(w) for w in works if w["harness_version"] == b and w["lane"] == lane]
            if xa or xb:
                ma, mb = _med(xa), _med(xb)
                ch = f"{(mb - ma) / ma * 100:+.0f}%" if ma and xb else "—"
                print(f"| {label} | {lane} | {_fmt(ma)} ({len(xa)}) | {_fmt(mb)} ({len(xb)}) | {ch}{' (표본 부족)' if min(len(xa), len(xb)) < 5 else ''} |")
    ga = [sum(total(r) for r in g["roles"].values()) for g in groups.values() if g["version"] == a]
    gb = [sum(total(r) for r in g["roles"].values()) for g in groups.values() if g["version"] == b]
    if ga or gb:
        ma, mb = _med(ga), _med(gb)
        ch = f"{(mb - ma) / ma * 100:+.0f}%" if ma and gb else "—"
        print(f"| 브랜치 전체 | — | {_fmt(ma)} ({len(ga)}) | {_fmt(mb)} ({len(gb)}) | {ch}{' (표본 부족)' if min(len(ga), len(gb)) < 5 else ''} |")


def main():
    p = argparse.ArgumentParser(prog="harness usage", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--since")
    p.add_argument("--compare", nargs=2, metavar=("A", "B"))
    a = p.parse_args()
    since = _ts(a.since + "T00:00:00+00:00") if a.since else None
    if a.compare:
        compare(*a.compare, since=since)
    else:
        report(since)


if __name__ == "__main__":
    main()
