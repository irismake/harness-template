#!/usr/bin/env python3
"""
자동 릴리스 (템플릿 레포 전용 — .github/workflows/release.yml 이 Template CI 통과 후 실행한다).

  1. 지난 릴리스 이후 main 커밋(first-parent = Squash 커밋)을 Conventional Commit 으로 분석
       feat → minor / fix · perf · refactor · ci · build · revert → patch / 제목에 ! 또는 본문 BREAKING CHANGE → major
       docs · chore · test · style 만 있으면 릴리스 없음
  2. release 브랜치에 릴리스 커밋 생성: 트리 = main 커밋 + VERSION + CHANGELOG(새 항목을 위에 추가)
     부모 = 이전 release · 이번 main 커밋 → release 는 항상 fast-forward, main 이력도 포함
  3. 태그 vX.Y.Z (annotated) · release 브랜치 push

main 은 보호 브랜치라 건드리지 않는다. VERSION · CHANGELOG 는 release 브랜치(= 프로젝트가 받는 하네스)에만 있다.

사용: release.py --main <sha> [--bump auto|patch|minor|major] [--remote origin] [--dry-run]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

RELEASE = "release"
TYPE_BUMP = {"feat": "minor", "fix": "patch", "perf": "patch", "refactor": "patch", "ci": "patch",
             "build": "patch", "revert": "patch"}
NO_RELEASE = {"docs", "chore", "test", "style"}
ORDER = ["major", "minor", "patch"]
SECTION = {"feat": "기능", "fix": "수정", "perf": "성능", "refactor": "구조 개선", "ci": "CI · 프로젝트 템플릿",
           "build": "빌드", "revert": "되돌림"}
SUBJECT_RE = re.compile(r"^(\w+)(\([^)]*\))?(!)?: (.+)$")
CHANGELOG_HEADER = "# 변경 기록\n\n프로젝트는 `.harness/core/harness update` · Dependabot 업데이트 PR 로 받을 때 이 파일의 변경을 본다. 자동 릴리스가 커밋 제목으로 만든다.\n"


def git(*args, env=None, input=None):
    r = subprocess.run(["git", *args], capture_output=True, text=True, env={**os.environ, **(env or {})}, input=input)
    if r.returncode != 0:
        sys.exit(f"git {' '.join(args)} 실패: {r.stderr.strip()}")
    return r.stdout.strip()


def ref_exists(ref):
    return subprocess.run(["git", "rev-parse", "-q", "--verify", ref], capture_output=True).returncode == 0


def classify(subject, body):
    m = SUBJECT_RE.match(subject)
    if not m:
        return None, None
    kind = m.group(1)
    if m.group(3) or "BREAKING CHANGE" in body:
        return kind, "major"
    if kind in NO_RELEASE:
        return kind, None
    return kind, TYPE_BUMP.get(kind)


def next_version(prev, bump):
    major, minor, patch = (int(x) for x in prev.split("."))
    if bump == "major":
        return f"{major + 1}.0.0" if major > 0 else f"0.{minor + 1}.0"  # 1.0 전에는 깨지는 변경도 minor
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--main", required=True)
    p.add_argument("--bump", default="auto", choices=["auto", "patch", "minor", "major"])
    p.add_argument("--remote", default="origin")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    remote_release = f"{a.remote}/{RELEASE}"
    main_sha = git("rev-parse", f"{a.main}^{{commit}}")
    if not ref_exists(remote_release):
        sys.exit(f"{remote_release} 가 없다 — 첫 릴리스는 수동으로 만든다")
    release_sha = git("rev-parse", remote_release)
    released_main = git("merge-base", release_sha, main_sha)
    if released_main == main_sha:
        print(f"릴리스 없음: {main_sha[:7]} 는 이미 릴리스에 들어 있다")
        return

    log = git("log", "--first-parent", "--format=%H%x1f%s%x1f%b%x1e", f"{released_main}..{main_sha}")
    entries, bumps = [], []
    for raw in filter(None, (r.strip() for r in log.split("\x1e"))):
        sha, subject, body = (raw.split("\x1f") + ["", ""])[:3]
        kind, bump = classify(subject, body)
        entries.append((kind, subject, sha))
        if bump:
            bumps.append(bump)
    bump = a.bump if a.bump != "auto" else next((b for b in ORDER if b in bumps), None)
    if not bump:
        print(f"릴리스 없음: 커밋 {len(entries)}개가 모두 docs · chore · test · style (또는 형식 밖)")
        return

    prev = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*.[0-9]*.[0-9]*", release_sha).lstrip("v")
    version = next_version(prev, bump)
    tag = f"v{version}"
    if ref_exists(f"refs/tags/{tag}"):
        sys.exit(f"태그 {tag} 가 이미 있다")

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"## {version} — {date}", ""]
    for kind in SECTION:
        items = [s for k, s, _ in entries if k == kind]
        if items:
            lines += [f"### {SECTION[kind]}", "", *(f"- {s}" for s in items), ""]
    others = [s for k, s, _ in entries if k not in SECTION]
    if others:
        lines += ["### 기타 (릴리스 판단에는 쓰지 않음)", "", *(f"- {s}" for s in others), ""]
    section = "\n".join(lines)
    old = subprocess.run(["git", "show", f"{release_sha}:CHANGELOG.md"], capture_output=True, text=True).stdout
    body = old.split("\n## ", 1)[1] if "\n## " in old else ""
    changelog = CHANGELOG_HEADER + "\n" + section + ("\n## " + body if body else "")

    print(f"{prev} → {version} ({bump}) · main {main_sha[:7]} · 커밋 {len(entries)}개\n\n{section}")
    if a.dry_run:
        return

    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
        git("read-tree", main_sha, env=env)
        for name, content in (("VERSION", version + "\n"), ("CHANGELOG.md", changelog)):
            blob = git("hash-object", "-w", "--stdin", input=content)
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{name}", env=env)
        tree = git("write-tree", env=env)
    commit = git("commit-tree", tree, "-p", release_sha, "-p", main_sha, "-m", f"release: {tag}\n\n{section}")
    git("tag", "-a", tag, commit, "-m", f"harness {version}")
    git("push", a.remote, f"{commit}:refs/heads/{RELEASE}", f"refs/tags/{tag}")
    print(f"\n✓ {tag} 릴리스 ({commit[:7]}) — release 브랜치 이동")
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a") as f:
            f.write(f"## 하네스 {tag}\n\n{prev} → {version} ({bump}), main `{main_sha[:7]}`\n\n{section}\n")


if __name__ == "__main__":
    main()
