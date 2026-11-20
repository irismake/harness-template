#!/usr/bin/env python3
"""
변경분에서 규칙 위반을 결정적으로 찾는다. 위반이 있으면 exit 1.

사용 (.harness/core/harness check-code … 와 같다):
  check_code.py                  # 기준 브랜치(config base_branch) 이후 변경 + 커밋 안 된 변경 · 새 파일
  check_code.py --base origin/main
  check_code.py --staged         # stage 한 변경만 (git pre-commit)
  check_code.py --file <경로>     # 파일 하나 (Claude 편집 직후 훅)
  … --lint                       # 팩의 포맷 · 정적 분석도 바뀐 파일에 실행 (도구가 없으면 건너뜀 — CI 가 다시 한다)

검사
  공통   secret-file (키 · 인증서 · .env 커밋) / secret-value (형식이 확실한 키 · 토큰 값) /
         layer (config.json "layers" — 경로별 금지 import) / tdd (TDD Guard 가 켜져 있으면 RED → GREEN 완료 여부, scripts/tdd.py) /
         trace (요구사항 추적이 켜져 있으면 REQ → 시나리오 → 테스트 연결, scripts/traceability.py)
  팩     .harness/core/packs/<pack>/checks.py   (예: flutter — print · 로그 속 인증 정보)
  프로젝트 .harness/checks.py (있으면)          (프로젝트 고유 검사 — feedback 스킬이 추가)
추가된 줄 · 새 파일만 본다. 이미 있던 위반은 세지 않는다.
판단이 필요한 것(요구사항 충족 · 설계 적합성)은 검사하지 않는다 → reviewer.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import events  # noqa: E402
import tdd  # noqa: E402
import traceability as trace_check  # noqa: E402
from lib import LOCAL_DIRS, ROOT, git, glob_regex, load_checks, load_config  # noqa: E402

SECRET_VALUE_RES = [
    ("개인 키", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----")),
    ("GitHub 토큰", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{50,})\b")),
    ("AWS 액세스 키", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack 토큰", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API 키", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("AI API 키", re.compile(r"\bsk-(ant-|proj-)?[A-Za-z0-9_-]{32,}")),
    ("Stripe 비밀 키", re.compile(r"\b(sk|rk)_live_[A-Za-z0-9]{20,}")),
]
IMPORT_RE = re.compile(r"""^\s*(import|export|from|require|using)\b.*?['"]?([^'";\s]+)['"]?""")
MAX_SCAN_BYTES = 2_000_000
CORE_RULE = ".harness/core/rules/core.md"


class Context:
    """팩 · 프로젝트 검사 모듈에 넘기는 것."""

    def __init__(self, cfg, added, new):
        self.cfg, self.added, self.new, self.root = cfg, added, new, ROOT
        self.problems = []

    def report(self, rule, path, line, message, doc):
        self.problems.append(f"[{rule}] {path}:{line} — {message} (규칙: {doc})")
        if os.environ.get("GITHUB_ACTIONS") == "true":  # PR 화면의 해당 줄에 표시
            print(f"::error file={path},line={line},title=하네스 {rule}::{message} ({doc})")

    def whole_file(self, path):
        return whole_file(path)

    @staticmethod
    def is_comment(text):
        return text.strip().startswith(("//", "/*", "*", "#", "///"))


def parse_added(diff):
    """unified diff(-U0) → {경로: [(줄번호, 내용)]}"""
    result, path, line_no = {}, None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            line_no = int(re.search(r"\+(\d+)", raw).group(1))
        elif raw.startswith("+") and path:
            result.setdefault(path, []).append((line_no, raw[1:]))
            line_no += 1
    return result


def whole_file(path):
    file = ROOT / path
    try:
        if file.is_symlink() or file.stat().st_size > MAX_SCAN_BYTES:
            return []
        return list(enumerate(file.read_text(errors="ignore").splitlines(), 1))
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return []


def changes(args):
    """{경로: [(줄번호, 추가된 줄)]}, 새 파일 집합"""
    if args.file:
        rel = os.path.relpath(Path(args.file).resolve(), ROOT)
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--error-unmatch", rel],
                                 capture_output=True).returncode == 0
        if not tracked:
            return {rel: whole_file(rel)}, {rel}
        has_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", "HEAD"], capture_output=True).returncode == 0
        return parse_added(git("diff", "-U0", "--no-color", *(["HEAD"] if has_head else ["--cached"]), "--", rel)), set()
    if args.staged:
        added = parse_added(git("diff", "--cached", "-U0", "--no-color", "--diff-filter=AM"))
        new = set(git("diff", "--cached", "--name-only", "--diff-filter=A").split("\n")) - {""}
        return added, new
    base = git("merge-base", args.base, "HEAD", check=False).strip() or args.base
    added = parse_added(git("diff", "-U0", "--no-color", "--diff-filter=AM", base))
    new = set(git("diff", "--name-only", "--diff-filter=A", base).split("\n")) - {""}
    for rel in git("ls-files", "--others", "--exclude-standard").split("\n"):
        if rel:
            added[rel] = whole_file(rel)
            new.add(rel)
    return added, new


def core_checks(ctx):
    cfg = ctx.cfg
    secret_files = [re.compile(p) for p in cfg.get("secret_files", [])]
    allow = [re.compile(p) for p in cfg.get("secret_value_allow", [])]
    for path in sorted(ctx.new):
        if any(p.search(path) for p in secret_files):
            ctx.report("secret-file", path, 1, "키 · 인증서 · 환경변수 · 서명 설정 파일은 커밋하지 않는다", CORE_RULE)
    for path, lines in sorted(ctx.added.items()):
        if path.startswith(".harness/core") or any(p.search(path) for p in allow):
            continue
        for no, text in lines:
            for label, pattern in SECRET_VALUE_RES:
                if pattern.search(text):
                    ctx.report("secret-value", path, no, f"{label}로 보이는 값이 들어 있다 — 제거하고 키를 폐기 · 재발급한다", CORE_RULE)

    for layer in cfg.get("layers", []):
        files = glob_regex(layer["files"])
        forbid = layer.get("forbid", [])
        for path, lines in sorted(ctx.added.items()):
            if not files.match(path):
                continue
            for no, text in lines:
                if IMPORT_RE.match(text) and (hit := next((f for f in forbid if f in text), None)):
                    ctx.report("layer", path, no, f"{layer.get('message', '금지된 의존')} ('{hit}')",
                               layer.get("rule", ".harness/rules/architecture.md"))


def default_base(cfg):
    branch = cfg.get("base_branch", "main")
    for ref in (f"origin/{branch}", branch):
        if subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "-q", ref], capture_output=True).returncode == 0:
            return ref
    if subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "-q", "HEAD"], capture_output=True).returncode == 0:
        return "HEAD"
    return "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # 빈 트리 (첫 커밋 전)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--base")
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--file")
    parser.add_argument("--lint", action="store_true")
    args = parser.parse_args()
    cfg = load_config()
    if not (args.staged or args.file):
        args.base = args.base or default_base(cfg)

    added, new = changes(args)
    # 생성물 · 서브모듈 포인터는 보지 않는다
    added = {p: l for p, l in added.items() if not p.startswith((".harness/core", ".claude/", *LOCAL_DIRS))}
    new = {p for p in new if not p.startswith(LOCAL_DIRS)}
    ctx = Context(cfg, added, new)
    core_checks(ctx)
    mode = "staged" if args.staged else "file" if args.file else "base"
    tdd.check(ctx, mode)
    trace_check.check(ctx, mode)
    modules = load_checks(cfg)
    for m in modules:
        if hasattr(m, "check"):
            m.check(ctx)
    if args.lint:
        paths = sorted(p for p in set(added) | new if (ROOT / p).is_file())
        for m in modules:
            if hasattr(m, "lint"):
                m.lint(ctx, paths)

    rule_ids = [m.group(1) for p in ctx.problems if (m := re.match(r"\[([\w-]+)\]", p))]
    events.record("fail" if ctx.problems else "pass", check="code", rules=rule_ids,
                  paths=sorted({m.group(1) for p in ctx.problems if (m := re.match(r"\[[\w-]+\] ([^:]+):", p))}))
    if ctx.problems:
        print("규칙 위반:")
        for p in ctx.problems:
            print(f"  {p}")
        sys.exit(1)
    scope = "stage 된 변경" if args.staged else args.file or f"{args.base} 이후 변경"
    print(f"코드 검사 통과 ({scope}, 파일 {len(added)}개)")


if __name__ == "__main__":
    main()
