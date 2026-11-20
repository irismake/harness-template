#!/usr/bin/env python3
"""
승격 PR 사전 확인 (pr 스킬) — 모두 통과해야 승격 PR 을 만든다. 조회만 한다 (PR 생성 · 머지 · push 안 함).

  1. head → base 가 프로젝트 승격 경로(config.json "promotion", 예: [["dev","staging"],["staging","main"]])에 있다
  2. 원격에 head · base 가 있다
  3. head 에 base 에 없는 커밋이 있다 (빈 diff 아님)
  4. 같은 head → base 로 열린 PR 이 없다 (있으면 그 PR 을 알려 준다)
  5. head 최신 커밋의 검사(check run)가 모두 끝났고 성공 · 건너뜀 · 중립뿐이다

사용: harness pr check-promotion <head> <base> [--remote origin]
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import ROOT, git, load_config  # noqa: E402

GH = os.environ.get("HARNESS_GH", "gh")
OK_CONCLUSIONS = {"success", "skipped", "neutral"}


def gh(*args):
    r = subprocess.run([GH, *args], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} 실패: {r.stderr.strip()[:200]}")
    return r.stdout


def check(cfg, head, base, remote="origin"):
    problems, notes = [], []
    paths = [tuple(p) for p in cfg.get("promotion", [])]
    if not paths:
        return ["config.json 에 승격 경로(promotion)가 없다 — 프로젝트 브랜치 전략을 먼저 정한다"], notes
    if (head, base) not in paths:
        problems.append(f"{head} → {base} 는 승격 경로가 아니다 (허용: {', '.join(f'{a} → {b}' for a, b in paths)})")
    heads = git("ls-remote", "--heads", remote, head, base, check=False)
    for b in (head, base):
        if f"refs/heads/{b}" not in heads:
            problems.append(f"원격 {remote} 에 {b} 브랜치가 없다")
    if problems:
        return problems, notes
    git("fetch", "-q", remote, head, base, check=False)
    ahead = git("rev-list", "--count", f"{remote}/{base}..{remote}/{head}", check=False).strip()
    if ahead in ("", "0"):
        problems.append(f"{head} 에 {base} 에 없는 커밋이 없다 (빈 승격)")
    else:
        notes.append(f"{base} 에 없는 커밋 {ahead}개")
    try:
        prs = json.loads(gh("pr", "list", "--head", head, "--base", base, "--state", "open", "--json", "number,url") or "[]")
        if prs:
            problems.append(f"이미 열린 승격 PR 이 있다: {prs[0]['url']} — 새로 만들지 않고 이 PR 을 보고한다")
        repo = json.loads(gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"]
        sha = git("rev-parse", f"{remote}/{head}").strip()
        runs = json.loads(gh("api", f"repos/{repo}/commits/{sha}/check-runs", "--jq", ".check_runs | map({name, status, conclusion})") or "[]")
        if not runs:
            problems.append(f"{head} 최신 커밋({sha[:7]})에 검사 결과가 없다")
        for r in runs:
            if r.get("status") != "completed":
                problems.append(f"검사가 아직 끝나지 않았다: {r['name']}")
            elif r.get("conclusion") not in OK_CONCLUSIONS:
                problems.append(f"검사 실패: {r['name']} ({r.get('conclusion')})")
        if runs and not problems:
            notes.append(f"검사 {len(runs)}개 통과 ({sha[:7]})")
    except (RuntimeError, ValueError, KeyError) as e:
        problems.append(f"GitHub 조회 실패 — 확인하지 못했다: {e}")
    return problems, notes


def main():
    p = argparse.ArgumentParser(prog="harness pr", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check-promotion")
    s.add_argument("head")
    s.add_argument("base")
    s.add_argument("--remote", default="origin")
    a = p.parse_args()
    problems, notes = check(load_config(), a.head, a.base, a.remote)
    for n in notes:
        print(f"  ✓ {n}")
    if problems:
        print(f"[하네스] 승격 PR 을 만들지 않는다 ({a.head} → {a.base}):")
        for x in problems:
            print(f"  - {x}")
        sys.exit(1)
    print(f"✓ 승격 PR 조건 통과: {a.head} → {a.base} (PR 생성은 사용자 확인 후 · 머지는 사용자)")


if __name__ == "__main__":
    main()
