"""
하네스 공통 — 경로 · 설정 · 팩 로딩.

배치: 프로젝트/.harness/core/ (= 이 템플릿 레포, git 서브모듈)
  CORE = .harness/core          공유 하네스 (프로젝트에서 고치지 않는다)
  ROOT = 프로젝트 루트          (.harness/core 의 두 단계 위)
  HARNESS = ROOT/.harness       프로젝트 소유 (config.json · rules/ · decisions/ · feedback-log.md)

템플릿 레포를 직접 시험할 때는 HARNESS_PROJECT_ROOT 로 프로젝트 루트를 지정한다.
"""
import copy
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]


def _project_root():
    env = os.environ.get("HARNESS_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    if CORE.parent.name == ".harness":
        return CORE.parent.parent
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(out.stdout.strip() or ".").resolve()


ROOT = _project_root()
HARNESS = ROOT / ".harness"
CONFIG_PATH = HARNESS / "config.json"
OUT = HARNESS / "out"

# 모든 팩 · 프로젝트에 공통인 기본값. 팩(pack.json) → 프로젝트(config.json) 순서로 덮어쓴다.
# 리스트는 이어 붙이고(중복 제거), 값은 덮어쓴다.
DEFAULTS = {
    "pack": None,
    "design_done": False,
    "base_branch": "main",
    "protected_branches": ["main"],
    "branch_prefixes": ["feat", "fix", "refactor", "chore", "docs", "test", "style", "ci", "hotfix"],
    "commit_types": ["feat", "fix", "refactor", "chore", "docs", "test", "style", "ci", "build", "perf", "revert"],
    "always_loaded_rules": ["core.md", "project.md"],
    "source_dirs": [],
    "test_dirs": [],
    "risk_areas": [],
    "commands": {},
    "layers": [],
    # TDD Guard (scripts/tdd.py) — 기본 꺼짐. project-design 이 테스트 정책에 따라 켜고 대상 경로를 채운다
    "tdd": {"enabled": False, "paths": [], "exclude": []},
    # 요구사항 추적 (scripts/traceability.py) — 기본 꺼짐. REQ → 시나리오 → 테스트 연결을 문서 · 코드에서 검사
    "trace": {"enabled": False},
    "secret_files": [
        r"\.(p8|p12|pem|key|cer|mobileprovision|jks|keystore)$",
        r"(^|/)\.env(\.[\w.-]+)?$",
    ],
    "secret_value_allow": [],
    "protected": {
        "bash_deny": [
            [r"\bgit\s+reset\b[^;&|]*--hard\b", "git reset --hard 는 커밋 안 된 작업을 지운다"],
            [r"\bgit\s+clean\b[^;&|]*\s-[a-zA-Z]*f", "git clean -f 는 추적 안 된 파일을 지운다"],
            [r"\bgit\s+push\b[^;&|]*(\s--force\b|\s--force-with-lease\b|\s-[a-zA-Z]*f\b|\s\+\S)", "강제 push 금지"],
            [r"\bgit\s+push\b[^;&|]*(\s--delete\b|\s-d\b|\s:\S)", "원격 브랜치 삭제 금지"],
            [r"\bgh\s+pr\s+merge\b", "머지는 사용자가 한다"],
            [r"\bgh\s+workflow\s+run\b", "워크플로 수동 실행(배포)은 사용자가 한다"],
            [r"\bgh\s+release\s+(create|delete|edit|upload)\b", "릴리스 · 태그는 사용자가 만든다"],
            [r"\bgh\s+secret\b", "GitHub Secret 은 건드리지 않는다"],
            [r"(^|[;&|(]\s*|\bexec\s+)fastlane(\s|$)", "fastlane(배포 · 서명)은 CD 와 사용자만 실행한다"],
        ],
        "bash_ask": [
            [r"\bgit\s+push\b", "push 는 사용자 승인 후에만"],
            [r"\bgh\s+pr\s+(create|edit|close|ready)\b", "PR 생성 · 변경은 사용자 승인 후에만"],
            [r"\bgh\s+api\b[^;&|]*(-X|--method)\s*(POST|PUT|PATCH|DELETE)\b", "GitHub 설정 · 데이터 변경은 사용자 승인 후에만"],
            [r"\bgit\s+submodule\s+update\b[^;&|]*--remote", "하네스 업데이트는 사용자 승인 후에만"],
            [r"\b(harness|tdd\.py)\b[^;&|]*\btdd\s+skip\b|\btdd\.py\s+skip\b", "TDD 예외는 사용자 승인 후에만"],
        ],
        "file_deny": [
            [r"(^|/)\.harness/core/", "공유 하네스(서브모듈)는 프로젝트에서 고치지 않는다 — 템플릿 레포에서 고친다"],
            [r"(^|/)\.env(\.[\w.-]+)?$", "환경변수 · 비밀 설정은 고치지 않는다"],
            [r"\.(p8|p12|pem|cer|mobileprovision|jks|keystore)$", "인증서 · 키 파일은 다루지 않는다"],
            [r"(^|/)\.git/", ".git 내부는 직접 고치지 않는다"],
        ],
        "file_ask": [
            [r"(^|/)\.github/", "CI/CD 설정 변경은 사용자 확인 필요"],
            [r"(^|/)\.claude/settings[^/]*\.json$", "훅 · 권한 설정 변경은 사용자 확인 필요 (하네스 우회 방지)"],
            [r"(^|/)\.harness/config\.json$", "하네스 설정 변경은 사용자 확인 필요 (하네스 우회 방지)"],
            [r"(^|/)\.harness/checks\.py$", "프로젝트 검사 변경은 사용자 확인 필요 (하네스 우회 방지)"],
            [r"(^|/)\.harness/tdd-skip\.json$", "TDD 예외 변경은 사용자 확인 필요 (하네스 우회 방지)"],
            [r"(^|/)fastlane/", "배포 설정 변경은 사용자 확인 필요"],
        ],
    },
}


def merge(base, over):
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = merge(base[k], v) if k in base else v
        return out
    if isinstance(base, list) and isinstance(over, list):
        out = list(base)
        for v in over:
            if v not in out:
                out.append(v)
        return out
    return over


def read_project_config():
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text())


def pack_dir(name):
    return CORE / "packs" / name if name else None


def load_config():
    project = read_project_config()
    cfg = copy.deepcopy(DEFAULTS)
    name = project.get("pack")
    if name and (pack_dir(name) / "pack.json").exists():
        cfg = merge(cfg, json.loads((pack_dir(name) / "pack.json").read_text()))
    return merge(cfg, project)


def _load_module(path, name):
    if not path or not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_checks(cfg):
    """[팩 검사 모듈, 프로젝트 검사 모듈(.harness/checks.py)] — 없는 것은 빠진다."""
    mods = [
        _load_module(pack_dir(cfg.get("pack")) / "checks.py" if cfg.get("pack") else None, "pack_checks"),
        _load_module(HARNESS / "checks.py", "project_checks"),
    ]
    return [m for m in mods if m]


def git(*args, cwd=None, check=True):
    return subprocess.run(["git", "-C", str(cwd or ROOT), *args], capture_output=True, text=True, check=check).stdout


def tracked_files():
    """커밋된 파일 + 아직 add 하지 않은 새 파일 (gitignore 제외)"""
    return [f for f in git("ls-files", "--cached", "--others", "--exclude-standard", check=False).split("\n") if f]


def glob_regex(pattern):
    """paths frontmatter 의 glob(**, *, ?) → 정규식"""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + "$")


def front_matter(text):
    """--- 블록 → ({키: 값}, [paths])"""
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, []
    body = m.group(1)
    fields = dict(re.findall(r"^(\w+):[ \t]*(\S.*)$", body, re.M))
    paths = []
    pm = re.search(r"^paths:\s*\n((?:\s*-\s*.+\n?)+)", body, re.M)
    if pm:
        paths = re.findall(r'^\s*-\s*"?([^"\n]+?)"?\s*$', pm.group(1), re.M)
    return fields, paths
