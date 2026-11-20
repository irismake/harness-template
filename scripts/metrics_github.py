#!/usr/bin/env python3
"""
GitHub 지표 — 실제 PR · CI 이력으로 하네스 버전별 · 도입 전후를 비교한다. 조회만 한다 (gh 인증 필요).

정의 (출력에도 표시)
  작업 PR          기간 안에 머지된 PR 중 승격 · 역반영(head 가 보호 브랜치 · 승격 경로 출발점)을 뺀 것
  유형             PR 제목 접두사(`feat: …`) → 없으면 브랜치 접두사(`feat/…`) → 그 밖은 other
  버그 수정 비율   fix / (feat + fix + refactor)
  하네스 버전      PR 머지 커밋의 .harness/core 포인터 → 릴리스 버전. .harness/core 가 없으면 "도입 전", 커밋을 로컬에서 못 찾으면 "?"
  CI 최초 통과율   pull_request 실행을 (워크플로, 출발 브랜치)별로 묶어 첫 실행이 성공한 비율. 취소 · 진행 중 제외
  CI 성공률        끝난 실행(success · failure) 중 success 비율
  실패 job         실패한 실행의 job 이름별 횟수 (최근 실패 실행 최대 --max-failed 개만 조회)
  CI 실행의 버전   실행 head 커밋의 .harness/core (로컬에 없으면 "?")

사용: harness metrics github [--since 2026-11-01] [--until 2026-12-01] [--max-failed 100]
결과: 표준 출력(Markdown) · .harness/out/metrics/github-<날짜>.json (gitignore)
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import usage  # noqa: E402
from lib import OUT, ROOT, git, load_config  # noqa: E402

GH = os.environ.get("HARNESS_GH", "gh")
TYPES = {"feat", "fix", "refactor", "perf", "chore", "ci", "build", "test", "docs", "style", "revert", "release"}
ALIASES = {"feature": "feat", "bugfix": "fix", "hotfix": "fix"}
PR_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED, first: 100, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number title headRefName baseRefName mergedAt mergeCommit { oid } commits { totalCount } }
    }
  }
}
"""


def gh(*args):
    r = subprocess.run([GH, *args], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"gh 조회 실패: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout or "null")


def _t(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _in(ts, since, until):
    return ts is not None and (since is None or ts >= since) and (until is None or ts < until)


def pr_type(pr):
    title_head = pr["title"].split(":", 1)[0] if ":" in pr["title"] else ""
    for raw in (title_head, pr["headRefName"].split("/", 1)[0]):
        k = raw.strip().lower().split("(", 1)[0].rstrip("!")
        k = ALIASES.get(k, k)
        if k in TYPES:
            return k
    return "other"


def rate(ok, n):
    return round(ok / n * 100, 1) if n else None


def fetch_prs(repo, since):
    owner, name = repo.split("/")
    out, cursor = [], None
    while True:
        args = ["api", "graphql", "-f", f"query={PR_QUERY}", "-F", f"owner={owner}", "-F", f"name={name}"]
        if cursor:
            args += ["-F", f"cursor={cursor}"]
        page = gh(*args)["data"]["repository"]["pullRequests"]
        out += page["nodes"]
        oldest = min((_t(p["mergedAt"]) for p in page["nodes"] if p.get("mergedAt")), default=None)
        if not page["pageInfo"]["hasNextPage"] or (since and oldest and oldest < since):
            return out
        cursor = page["pageInfo"]["endCursor"]


def fetch_runs(repo, since):
    runs, page = [], 1
    while True:
        data = gh("api", f"repos/{repo}/actions/runs?per_page=100&page={page}")
        batch = data.get("workflow_runs", [])
        runs += batch
        if len(batch) < 100 or (since and batch and _t(batch[-1]["created_at"]) < since):
            return runs
        page += 1


def collect(since, until, max_failed):
    cfg = load_config()
    repo = gh("repo", "view", "--json", "nameWithOwner")["nameWithOwner"]
    excluded_heads = set(cfg.get("protected_branches", [])) | {cfg.get("base_branch", "main")} | {a for a, _ in cfg.get("promotion", [])}
    git("fetch", "-q", "origin", check=False)

    prs = [p for p in fetch_prs(repo, since) if _in(_t(p.get("mergedAt")), since, until) and p["headRefName"] not in excluded_heads]
    by_version = defaultdict(list)
    for p in prs:
        p["type"] = pr_type(p)
        p["version"] = usage.version_for_commit((p.get("mergeCommit") or {}).get("oid"))
        by_version[p["version"]].append(p)

    runs = [r for r in fetch_runs(repo, since) if _in(_t(r["created_at"]), since, until)]
    for r in runs:
        r["version"] = usage.version_for_commit(r.get("head_sha"))
    failed = sorted((r for r in runs if r.get("conclusion") == "failure"), key=lambda r: r["created_at"], reverse=True)[:max_failed]
    failed_jobs = defaultdict(Counter)
    for r in failed:
        for j in gh("api", f"repos/{repo}/actions/runs/{r['id']}/jobs?per_page=100").get("jobs", []):
            if j.get("conclusion") == "failure":
                failed_jobs[r["version"]][f"{r['name']} / {j['name']}"] += 1

    def pr_stats(items):
        t = Counter(p["type"] for p in items)
        code = t["feat"] + t["fix"] + t["refactor"]
        return {"prs": len(items), "by_type": dict(t), "type_pct": {k: rate(v, len(items)) for k, v in t.items()},
                "fix_ratio_pct": rate(t["fix"], code), "median_commits": statistics.median([p["commits"]["totalCount"] for p in items]) if items else None}

    def ci_stats(items):
        done = [r for r in items if r.get("conclusion") in ("success", "failure")]
        first = {}
        for r in sorted((r for r in done if r["event"] == "pull_request"), key=lambda r: r["created_at"]):
            first.setdefault((r["name"], r.get("head_branch")), r)
        return {"runs": len(done), "success_pct": rate(sum(r["conclusion"] == "success" for r in done), len(done)),
                "first_pass_pct": rate(sum(r["conclusion"] == "success" for r in first.values()), len(first)), "first_pass_sample": len(first),
                "cancelled": sum(r.get("conclusion") == "cancelled" for r in items)}

    runs_by_version = defaultdict(list)
    for r in runs:
        runs_by_version[r["version"]].append(r)
    versions = sorted(set(by_version) | set(runs_by_version), key=lambda v: (v == "도입 전", v == "?", v), reverse=False)
    return {"repo": repo, "range": [since.isoformat() if since else None, until.isoformat() if until else None],
            "excluded_heads": sorted(excluded_heads), "failed_runs_checked": len(failed),
            "all": {"pr": pr_stats(prs), "ci": ci_stats(runs), "failed_jobs": dict(sum(failed_jobs.values(), Counter()))},
            "by_version": {v: {"pr": pr_stats(by_version[v]), "ci": ci_stats(runs_by_version[v]), "failed_jobs": dict(failed_jobs[v])} for v in versions}}


def to_markdown(res):
    lines = [f"## GitHub 지표 — {res['repo']} ({res['range'][0] or '처음'} ~ {res['range'][1] or '지금'})", "",
             "| 하네스 | 작업 PR | 유형 (비율) | 버그 수정 비율 | PR 당 커밋 | CI 실행 | CI 성공률 | CI 최초 통과율 (표본) | 실패 job 상위 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for label, d in [("전체", res["all"])] + list(res["by_version"].items()):
        pr, ci = d["pr"], d["ci"]
        types = ", ".join(f"{k} {v}({pr['type_pct'][k]}%)" for k, v in sorted(pr["by_type"].items(), key=lambda x: -x[1]))
        top = ", ".join(f"{k} {n}" for k, n in Counter(d["failed_jobs"]).most_common(3)) or "—"
        lines.append(f"| {label} | {pr['prs']} | {types or '—'} | {pr['fix_ratio_pct'] if pr['fix_ratio_pct'] is not None else '—'}% | "
                     f"{pr['median_commits'] if pr['median_commits'] is not None else '—'} | {ci['runs']} | {ci['success_pct'] if ci['success_pct'] is not None else '—'}% | "
                     f"{ci['first_pass_pct'] if ci['first_pass_pct'] is not None else '—'}% ({ci['first_pass_sample']}) | {top} |")
    lines += ["", f"- 작업 PR 에서 뺀 출발 브랜치: {', '.join(res['excluded_heads'])}",
              f"- 실패 job 은 최근 실패 실행 {res['failed_runs_checked']}개를 조회했다",
              "- 정의: `harness metrics github -h`. 하네스 버전은 머지 커밋의 `.harness/core` 포인터로 판정한다 (\"도입 전\" = 하네스 없음)"]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(prog="harness metrics github", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--max-failed", type=int, default=100)
    a = p.parse_args()
    since = datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc) if a.since else None
    until = datetime.fromisoformat(a.until).replace(tzinfo=timezone.utc) if a.until else None
    res = collect(since, until, a.max_failed)
    out = OUT / "metrics"
    out.mkdir(parents=True, exist_ok=True)
    (OUT / ".gitignore").exists() or (OUT / ".gitignore").write_text("*\n")
    (out / f"github-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(to_markdown(res))


if __name__ == "__main__":
    main()
