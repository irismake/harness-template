#!/usr/bin/env python3
"""
요구사항 추적 — 요구사항(REQ) → 테스트 시나리오(TS) → 테스트 를 문서와 코드에서 기계로 대조한다. (config.json "trace.enabled" 로 켠다)

  요구사항 문서   requirement_docs 의 제목(#…) 또는 표 첫 칸에 정의된 REQ ID          예: #### CHAT-REQ-001 — 채팅방 생성
  시나리오 문서   scenario_docs 의 표 행: 첫 칸 = TS ID, 같은 행의 REQ ID = 연결된 요구사항  예: | CHAT-TS-001 | CHAT-REQ-001 | … |
  테스트          tests 파일에서 test_marker 정규식(그룹 1 = TS ID)이 맞는 곳              예: @pytest.mark.scenario("CHAT-TS-001")

검사 (오류면 실패)
  1. 테스트에 붙은 ID 는 시나리오 문서에 있다 · 형식이 맞다
  2. 한 ID 는 테스트 하나에만 붙는다 (one_to_one)
  3. 시나리오 ID 는 문서 안팎에서 중복되지 않는다
  4. 시나리오는 모두 테스트에 연결된다 — 문서 상단 "> 상태:" 에 pending_mark(기본 "구현 전")가 있으면 경고만 (문서 단계)
  5. 시나리오 행이 가리키는 REQ 는 요구사항 문서에 정의돼 있다 (requirement_docs 를 설정했을 때)
  6. 정의된 REQ 마다 시나리오가 하나 이상 있다 — requirement_coverage: error | warn(기본) | off

사용: harness trace                 # 전체 검사 + 요약
      harness trace CHAT-REQ-001    # 그 요구사항 → 시나리오 → 테스트 위치 (planner · reviewer 대조용)
      harness trace CHAT-TS-001     # 그 시나리오 → 요구사항 · 테스트 위치
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import ROOT, glob_regex, load_config, tracked_files  # noqa: E402

DEFAULTS = {
    "enabled": False,
    "requirement_docs": [],
    "scenario_docs": ["docs/**/test-scenarios.md"],
    "tests": [],                       # 비우면 config test_dirs 아래 전부
    "test_marker": None,               # 비우면 테스트 파일에 나오는 TS ID 를 모두 연결로 본다
    "scenario_id": r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-TS-\d{3}",
    "requirement_id": r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-REQ-\d{3}",
    "pending_mark": "구현 전",
    "one_to_one": True,
    "requirement_coverage": "warn",
}


def settings(cfg):
    return {**DEFAULTS, **(cfg.get("trace") or {})}


def enabled(cfg):
    return bool(settings(cfg)["enabled"])


def _match(globs, files):
    regs = [glob_regex(g) for g in globs]
    return [f for f in files if any(r.match(f) for r in regs)]


def collect(cfg):
    s = settings(cfg)
    files = tracked_files()
    ts_re, req_re = re.compile(s["scenario_id"]), re.compile(s["requirement_id"])
    row_re = re.compile(r"^\|\s*(" + s["scenario_id"] + r")\s*\|")
    def_res = [re.compile(r"^#+\s.*?\b(" + s["requirement_id"] + r")\b"),     # 제목: #### CHAT-REQ-001 — …
               re.compile(r"^\|\s*(" + s["requirement_id"] + r")\s*\|")]        # 표 첫 칸: | CHAT-REQ-001 | …
    errors, warnings = [], []

    # 요구사항 정의
    reqs = {}
    for doc in _match(s["requirement_docs"], files):
        for no, line in enumerate((ROOT / doc).read_text(errors="ignore").splitlines(), 1):
            m = next((r.match(line) for r in def_res if r.match(line)), None)
            if m:
                rid = m.group(1)
                if rid in reqs and reqs[rid][0] != doc:
                    errors.append((doc, no, f"요구사항 ID 중복: {rid} ({reqs[rid][0]}:{reqs[rid][1]})"))
                reqs.setdefault(rid, (doc, no))

    # 시나리오
    scenarios = {}   # id → (doc, line, [req], pending)
    for doc in _match(s["scenario_docs"], files):
        text = (ROOT / doc).read_text(errors="ignore")
        status = next((l for l in text.splitlines() if l.startswith("> 상태:")), "")
        pending = bool(s["pending_mark"]) and s["pending_mark"] in status
        for no, line in enumerate(text.splitlines(), 1):
            m = row_re.match(line)
            if not m:
                continue
            sid = m.group(1)
            if sid in scenarios:
                d, n = scenarios[sid][:2]
                errors.append((doc, no, f"시나리오 ID 중복: {sid} ({d}:{n})"))
                continue
            scenarios[sid] = (doc, no, sorted(set(req_re.findall(line))), pending)

    # 테스트
    test_globs = s["tests"] or [d.rstrip("/") + "/**" for d in cfg.get("test_dirs", [])]
    marker = re.compile(s["test_marker"]) if s["test_marker"] else re.compile(r"(" + s["scenario_id"] + r")")
    tests = defaultdict(list)  # id → [path:line]
    for path in _match(test_globs, files):
        try:
            lines = (ROOT / path).read_text(errors="ignore").splitlines()
        except OSError:
            continue
        for no, line in enumerate(lines, 1):
            for m in marker.finditer(line):
                tid = m.group(1)
                if not ts_re.fullmatch(tid):
                    errors.append((path, no, f"시나리오 ID 형식 오류: {tid!r}"))
                    continue
                tests[tid].append(f"{path}:{no}")

    # 판정
    for tid, locs in sorted(tests.items()):
        if tid not in scenarios:
            p, n = locs[0].rsplit(":", 1)
            errors.append((p, int(n), f"시나리오 문서에 없는 ID: {tid}"))
        if s["one_to_one"] and len(locs) > 1:
            p, n = locs[1].rsplit(":", 1)
            errors.append((p, int(n), f"테스트 여러 개에 붙은 ID: {tid} ({', '.join(locs)})"))
    for sid, (doc, no, rids, pending) in sorted(scenarios.items()):
        if sid not in tests:
            (warnings if pending else errors).append((doc, no, f"테스트가 없는 시나리오: {sid}"
                                                       + (" (문서 상태: 구현 전)" if pending else "")))
        if s["requirement_docs"]:
            for rid in rids:
                if rid not in reqs:
                    errors.append((doc, no, f"요구사항 문서에 정의되지 않은 REQ: {rid} ({sid})"))
    if s["requirement_docs"] and s["requirement_coverage"] != "off":
        covered = {r for v in scenarios.values() for r in v[2]}
        for rid, (doc, no) in sorted(reqs.items()):
            if rid not in covered:
                (errors if s["requirement_coverage"] == "error" else warnings).append(
                    (doc, no, f"시나리오가 없는 요구사항: {rid}"))
    return {"reqs": reqs, "scenarios": scenarios, "tests": tests, "errors": errors, "warnings": warnings}


def check(ctx, mode):
    """check_code.py 에서 호출 (종료 전 · verify · pre-commit · PR CI). 편집 직후(file)에는 돌리지 않는다."""
    if mode == "file" or not enabled(ctx.cfg):
        return
    for path, line, msg in collect(ctx.cfg)["errors"]:
        ctx.report("trace", path, line, msg, ".harness/core/scripts/traceability.py")


def show(data, ident):
    reqs, scenarios, tests = data["reqs"], data["scenarios"], data["tests"]
    if ident in reqs:
        doc, no = reqs[ident]
        print(f"{ident}  ({doc}:{no})")
        linked = [(sid, v) for sid, v in sorted(scenarios.items()) if ident in v[2]]
        if not linked:
            print("  시나리오 없음")
        for sid, (sdoc, sno, _, _) in linked:
            print(f"  └ {sid}  ({sdoc}:{sno})")
            print(f"      테스트: {', '.join(tests.get(sid, [])) or '없음'}")
    elif ident in scenarios:
        doc, no, rids, pending = scenarios[ident]
        print(f"{ident}  ({doc}:{no}){'  [구현 전]' if pending else ''}")
        print(f"  요구사항: {', '.join(rids) or '없음'}")
        print(f"  테스트: {', '.join(tests.get(ident, [])) or '없음'}")
    else:
        sys.exit(f"{ident} 를 요구사항 · 시나리오 문서에서 찾지 못했다")


def main():
    cfg = load_config()
    if not enabled(cfg):
        print("요구사항 추적 꺼짐 (config.json trace.enabled)")
        return
    data = collect(cfg)
    if len(sys.argv) > 1:
        show(data, sys.argv[1])
        return
    for path, line, msg in data["warnings"]:
        print(f"경고: {path}:{line} — {msg}")
    for path, line, msg in data["errors"]:
        print(f"오류: {path}:{line} — {msg}")
    linked = sum(1 for sid in data["scenarios"] if sid in data["tests"])
    print(f"요구사항 {len(data['reqs'])}개 · 시나리오 {len(data['scenarios'])}개 중 {linked}개가 테스트에 연결됨"
          f" (경고 {len(data['warnings'])}, 오류 {len(data['errors'])})")
    sys.exit(1 if data["errors"] else 0)


if __name__ == "__main__":
    main()
