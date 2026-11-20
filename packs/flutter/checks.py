"""
Flutter 팩 검사 — check_code.py 가 불러 쓴다. (형식은 프로젝트 검사 .harness/checks.py 의 예시이기도 하다)

  check(ctx)       추가된 줄에서 규칙 위반 찾기          logging · sensitive-log
  lint(ctx, paths) 바뀐 Dart 파일에 dart format · dart analyze (CI 와 같은 설정, 도구가 없으면 건너뜀)
  post_edit_match  Claude 편집 직후 훅이 검사할 파일인지
  command_vars     harness test 명령의 {flutter} · {dart} 값 (.fvmrc 가 있으면 fvm 사용)

ctx: added {경로: [(줄번호, 내용)]} · new {새 파일} · root · cfg · report(rule, path, line, message, doc) · is_comment(text)
"""
import os
import re
import shutil
import subprocess
import sys

RULE = ".harness/core/packs/flutter/rules/flutter.md"
GENERATED = re.compile(r"\.(g|freezed|gr|config|mocks|chopper)\.dart$")
PRINT_RE = re.compile(r"(?<![\w.])(print|debugPrint)\(")
LOG_CALL_RE = re.compile(r"(\b\w*[Ll]og(ger)?\.\w+|(?<![\w.])(log|print|debugPrint))\(")
INTERP_RE = re.compile(r"\$\{([^}]*)\}|\$([A-Za-z_]\w*)")
SENSITIVE_RE = re.compile(r"(?i)(token|password|passwd|secret|authorization|cookie|credential|api_?key|refresh|session_?id)")
MASKED_RE = re.compile(r"(?i)mask|redact|length|isEmpty|isNotEmpty|!= null|== null")


def _is_source(ctx, path):
    return path.endswith(".dart") and not GENERATED.search(path) and path.startswith(tuple(ctx.cfg.get("source_dirs", ["lib/"])))


def check(ctx):
    for path, lines in sorted(ctx.added.items()):
        if not _is_source(ctx, path):
            continue
        for no, text in lines:
            if ctx.is_comment(text):
                continue
            if PRINT_RE.search(text):
                ctx.report("logging", path, no, "print · debugPrint 대신 프로젝트 로거를 쓴다", RULE)
            if LOG_CALL_RE.search(text):
                exprs = [a or b for a, b in INTERP_RE.findall(text)]
                if any(SENSITIVE_RE.search(e) and not MASKED_RE.search(e) for e in exprs):
                    ctx.report("sensitive-log", path, no, "토큰 · 비밀번호 등 인증 정보를 로그에 넣지 않는다 (있음/없음 · 길이 같은 상태만)", RULE)


def post_edit_match(path):
    return path.endswith(".dart") and not GENERATED.search(path)


def _uses_fvm(root):
    return (root / ".fvmrc").exists() and shutil.which("fvm") is not None


def command_vars(root):
    fvm = _uses_fvm(root)
    return {"flutter": "fvm flutter" if fvm else "flutter", "dart": "fvm dart" if fvm else "dart"}


def _dart(root):
    if _uses_fvm(root):
        return ["fvm", "dart"]
    return ["dart"] if shutil.which("dart") else None


def lint(ctx, paths):
    files = [p for p in paths if p.endswith(".dart") and not GENERATED.search(p)]
    root = ctx.root
    if not files or not (root / "pubspec.yaml").exists():
        return
    dart = _dart(root)
    if not dart:
        print("dart 가 없어 포맷 · 정적 분석을 건너뜀 (CI 에서 검사)", file=sys.stderr)
        return
    r = subprocess.run([*dart, "format", "--output=none", "--set-exit-if-changed", *files],
                       cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        for line in r.stdout.splitlines():
            if line.startswith("Changed "):
                ctx.report("dart-format", line.removeprefix("Changed ").strip(), 1, "포맷이 다르다 → dart format <파일>", RULE)
    if not (root / ".dart_tool/package_config.json").exists():
        print("패키지가 아직 없어(flutter pub get 전) 정적 분석을 건너뜀", file=sys.stderr)
        return
    r = subprocess.run([*dart, "analyze", "--format=machine", *files], cwd=root, capture_output=True, text=True)
    for line in (r.stdout + r.stderr).splitlines():
        parts = line.split("|")
        if len(parts) >= 8 and parts[0] in {"ERROR", "WARNING", "INFO"}:
            rel = os.path.relpath(parts[3], root)
            ctx.report(f"analyze-{parts[0].lower()}", rel, parts[4], f"{parts[2].lower()}: {'|'.join(parts[7:])}", "analysis_options.yaml")
