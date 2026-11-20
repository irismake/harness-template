#!/usr/bin/env python3
"""
하네스 명령 (프로젝트 루트에서: .harness/core/harness <명령>)

  init <팩>          프로젝트에 하네스 설치 — 진입점 · 설정 · 링크 · git 훅 · CI · dependabot (있는 파일은 덮어쓰지 않는다)
  sync               규칙 · 역할 · 스킬 링크와 AGENTS.md 표를 원본에 맞춰 다시 만든다
  verify [--base R]  작업 마치기 전 검사 = check-rules + check-code --lint (수 초, 빌드 · 테스트 없음)
  check-rules        하네스 구성 검사
  check-code [...]   변경분 코드 검사 (--base · --staged · --file · --lint)
  test <대상>        관련 테스트만 실행 (config commands.test). 전체는 --all (보통 CI 가 한다)
  tdd status|skip|ci  TDD Guard 상태 · 예외(사용자 승인) · CI 의 RED 재현 검사
  trace [ID]         요구사항 추적 검사 · REQ/시나리오 하나의 연결(→ 시나리오 → 테스트 위치) 보기
  run <이름> [...]   config commands 의 명령 실행 (예: run codegen · run format · run analyze)
  update             공유 하네스(서브모듈)를 최신으로 받고 sync — 변경 내역을 보여 준다. 커밋은 직접
  stats [--since D]  로컬 검사 기록(.harness/out/events.jsonl) 집계
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync  # noqa: E402
import tdd  # noqa: E402
from lib import CONFIG_PATH, CORE, HARNESS, ROOT, git, load_checks, load_config, pack_dir  # noqa: E402

SCRIPTS = CORE / "scripts"
TEMPLATES = CORE / "templates"
# 코어 템플릿 → 프로젝트 위치
CORE_FILES = {
    "AGENTS.md": "AGENTS.md",
    "CLAUDE.md": "CLAUDE.md",
    "claude-settings.json": ".claude/settings.json",
    "project.md": ".harness/rules/project.md",
    "feedback-log.md": ".harness/feedback-log.md",
    "decisions-README.md": ".harness/decisions/README.md",
    "dependabot.yml": ".github/dependabot.yml",
}
GITIGNORE = [".harness/out/", ".claude/settings.local.json"]
# 정식 릴리스만 가리키는 브랜치 — 릴리스 워크플로가 CI 를 통과한 태그 커밋으로만 옮긴다.
# 프로젝트 서브모듈은 이 브랜치를 추적한다 (Dependabot · harness update 모두 이 기준).
RELEASE_BRANCH = "release"


def core_version():
    """릴리스 커밋에만 VERSION 이 있다 (main 은 개발 중)"""
    f = CORE / "VERSION"
    return f.read_text().strip() if f.exists() else "개발 중(main)"


def track_release_branch():
    """.gitmodules 에 branch = release 를 기록한다 (이미 있으면 그대로). 바꿨으면 True"""
    gm = ROOT / ".gitmodules"
    if CORE != HARNESS / "core" or not gm.exists():
        return False
    rel = os.path.relpath(CORE, ROOT)
    names = git("config", "-f", str(gm), "--get-regexp", r"submodule\..*\.path", check=False).splitlines()
    name = next((l.split()[0][len("submodule."):-len(".path")] for l in names if l.split()[-1] == rel), None)
    if not name:
        return False
    key = f"submodule.{name}.branch"
    if git("config", "-f", str(gm), "--get", key, check=False).strip():
        return False
    git("config", "-f", str(gm), key, RELEASE_BRANCH)
    return True


def py(script, *args, source=None):
    env = {**os.environ}
    if source:
        env.setdefault("HARNESS_SOURCE", source)
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=ROOT, env=env).returncode


def render(text, values):
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def cmd_init(args):
    if subprocess.run(["git", "-C", str(ROOT), "rev-parse"], capture_output=True).returncode != 0:
        sys.exit("git 저장소가 아닙니다. 먼저 git init 을 하세요.")
    if CORE != HARNESS / "core":
        print(f"⚠️  하네스가 .harness/core 에 있지 않습니다 ({CORE}). 서브모듈로 추가하세요:\n"
              "   git submodule add -b release https://github.com/irismake/harness-template .harness/core")
    existing = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    pack = args.pack or existing.get("pack")
    if not pack:
        packs = sorted(p.name for p in (CORE / "packs").iterdir() if (p / "pack.json").exists())
        sys.exit(f"팩을 지정하세요: harness init <팩>  (있는 팩: {', '.join(packs)})")
    if not (pack_dir(pack) / "pack.json").exists():
        sys.exit(f"팩 '{pack}' 이 없습니다.")
    pack_meta = json.loads((pack_dir(pack) / "pack.json").read_text())
    values = {"project_name": ROOT.name, "pack": pack}

    created = []
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(render((TEMPLATES / "config.json").read_text(), values))
        created.append(".harness/config.json")
    files = {TEMPLATES / src: dst for src, dst in CORE_FILES.items()}
    files.update({pack_dir(pack) / src: dst for src, dst in pack_meta.get("init_files", {}).items()})
    for src, dst in files.items():
        target = ROOT / dst
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(src.read_text(), values))
        created.append(dst)

    gi = ROOT / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    missing = [l for l in GITIGNORE + pack_meta.get("gitignore", []) if l not in lines]
    if missing:
        gi.write_text("\n".join(lines + ["", "# harness", *missing]).lstrip("\n") + "\n")
        created.append(".gitignore (하네스 항목)")

    if track_release_branch():
        created.append(f".gitmodules (branch = {RELEASE_BRANCH} — 정식 릴리스만 업데이트 대상)")

    cfg = load_config()
    links = sync.apply_links(cfg)
    sync.apply_agents_md(cfg)
    hooks = os.path.relpath(CORE / "githooks", ROOT)
    git("config", "core.hooksPath", hooks)
    for f in (CORE / "githooks").iterdir():
        f.chmod(0o755)

    print(f"✓ 하네스 {core_version()} 설치")
    for c in created:
        print(f"  + {c}")
    print(f"  + .claude/ 링크 {len([l for l in links if l.startswith('+')])}개 · AGENTS.md 표")
    print(f"  ✓ git 훅: core.hooksPath={hooks}")
    print("\n다음: Claude Code 또는 Codex 를 이 폴더에서 열고 \"<만들 앱> 을 만들고 싶어\" 라고 말하면 project-design 스킬로 설계를 시작합니다.")
    print("      설치 결과는 커밋하세요: git add -A && git commit -m \"chore: 하네스 설치\"")


def cmd_sync(_):
    cfg = load_config()
    changed = sync.apply_links(cfg)
    md = sync.apply_agents_md(cfg) if (ROOT / "AGENTS.md").exists() else False
    for c in changed:
        print(c)
    print(f"✓ sync: 링크 변경 {len(changed)}개{' · AGENTS.md 표 갱신' if md else ''}")


def cmd_verify(args):
    code = py("check_rules.py", source="verify")
    extra = ["--base", args.base] if args.base else []
    code |= py("check_code.py", "--lint", *extra, source="verify")
    if code == 0:
        print("✓ verify 통과 (빌드 · 전체 테스트는 CI 가 한다)")
    sys.exit(code)


def cmd_test(args):
    cfg = load_config()
    commands = cfg.get("commands", {})
    if args.all:
        cmd = commands.get("test_all")
    elif args.target:
        cmd = commands.get("test", "").replace("{target}", " ".join(shlex.quote(t) for t in args.target))
    else:
        sys.exit("테스트 대상을 지정하세요 (파일 · 폴더). 전체 테스트는 CI 가 한다 — 꼭 필요하면 --all")
    if not cmd:
        sys.exit("config.json 의 commands.test 가 없습니다.")
    runner = next((m.run_tests for m in reversed(load_checks(cfg)) if hasattr(m, "run_tests")), None)
    if runner:  # 팩이 결과를 구조화해 주면 TDD Guard 기록을 남긴다
        targets = [] if args.all else args.target
        results = runner(ROOT, targets)
        tdd.record_run(cfg, results)
        counts = {s: sum(1 for v in results.values() if v == s) for s in ("pass", "fail", "load_error")}
        print(f"테스트 파일 {len(results)}개: 통과 {counts['pass']} · 실패 {counts['fail']} · 컴파일 실패 {counts['load_error']}"
              + (" (TDD 기록 저장)" if tdd.enabled(cfg) else ""))
        sys.exit(0 if results and all(v == "pass" for v in results.values()) else 1)
    run_shell(cfg, cmd)


def run_shell(cfg, cmd):
    for m in load_checks(cfg):
        if hasattr(m, "command_vars"):
            for k, v in m.command_vars(ROOT).items():
                cmd = cmd.replace("{" + k + "}", v)
    print(f"$ {cmd}")
    sys.exit(subprocess.run(cmd, shell=True, cwd=ROOT).returncode)


def cmd_run(args):
    cfg = load_config()
    commands = cfg.get("commands", {})
    if args.name not in commands:
        sys.exit(f"명령 '{args.name}' 이 없습니다. 있는 명령: {', '.join(sorted(commands))}")
    run_shell(cfg, commands[args.name].replace("{target}", " ".join(shlex.quote(t) for t in args.extra)))


def cmd_update(_):
    if CORE != HARNESS / "core":
        sys.exit("서브모듈(.harness/core)로 설치된 프로젝트에서만 쓴다.")
    rel = os.path.relpath(CORE, ROOT)
    track_release_branch()
    old = git("rev-parse", "HEAD", cwd=CORE).strip()
    old_version = core_version()
    # .gitmodules 의 branch(release) 최신 커밋 = 최신 정식 릴리스
    subprocess.run(["git", "-C", str(ROOT), "submodule", "update", "--init", "--remote", rel], check=True)
    new = git("rev-parse", "HEAD", cwd=CORE).strip()
    if old == new:
        print(f"이미 최신 릴리스입니다 ({old_version}).")
        return
    print(f"하네스 {old_version} → {core_version()}  ({old[:7]} → {new[:7]})")
    print(git("log", "--oneline", f"{old}..{new}", cwd=CORE))
    print("CHANGELOG 변경:")
    print(git("diff", old, new, "--", "CHANGELOG.md", cwd=CORE) or "  (없음)")
    cmd_sync(None)
    py("check_rules.py")
    print("\n확인 후 커밋: git add .harness/core .claude AGENTS.md && git commit -m \"chore: 하네스 업데이트\"")


def cmd_stats(args):
    path = HARNESS / "out/events.jsonl"
    if not path.exists():
        print("기록 없음 (.harness/out/events.jsonl)")
        return
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    if args.since:
        rows = [r for r in rows if r["ts"] >= args.since]
    by_source = Counter((r["source"], r["result"]) for r in rows)
    rules = Counter(rule for r in rows for rule in r.get("rules", []))
    reasons = Counter(r["reason"] for r in rows if r.get("reason"))
    print(f"## 하네스 검사 기록 ({len(rows)}건{', ' + args.since + ' 이후' if args.since else ''})\n")
    print("| 실행 위치 | 결과 | 횟수 |\n|---|---|---|")
    for (s, res), n in sorted(by_source.items()):
        print(f"| {s} | {res} | {n} |")
    if rules:
        print("\n| 규칙 | 위반 |\n|---|---|")
        for k, n in rules.most_common():
            print(f"| {k} | {n} |")
    if reasons:
        print("\n| 실행 전 훅 차단 · 확인 이유 | 횟수 |\n|---|---|")
        for k, n in reasons.most_common():
            print(f"| {k} | {n} |")


def main():
    parser = argparse.ArgumentParser(prog="harness", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init")
    p.add_argument("pack", nargs="?")
    sub.add_parser("sync")
    p = sub.add_parser("verify")
    p.add_argument("--base")
    sub.add_parser("check-rules")
    sub.add_parser("check-code", add_help=False)
    p = sub.add_parser("test")
    p.add_argument("target", nargs="*")
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("run")
    p.add_argument("name")
    p.add_argument("extra", nargs="*")
    sub.add_parser("tdd", add_help=False)
    sub.add_parser("trace", add_help=False)
    sub.add_parser("update")
    p = sub.add_parser("stats")
    p.add_argument("--since")

    argv = sys.argv[1:]
    if argv[:1] == ["trace"]:
        sys.exit(py("traceability.py", *argv[1:]))
    if argv[:1] == ["tdd"]:
        sys.exit(py("tdd.py", *argv[1:]))
    if argv[:1] == ["check-code"]:
        sys.exit(py("check_code.py", *argv[1:]))
    if argv[:1] == ["check-rules"]:
        sys.exit(py("check_rules.py"))
    args = parser.parse_args(argv)
    {"init": cmd_init, "sync": cmd_sync, "verify": cmd_verify, "test": cmd_test, "run": cmd_run,
     "update": cmd_update, "stats": cmd_stats}[args.command](args)


if __name__ == "__main__":
    main()
