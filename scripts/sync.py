"""
규칙 · 역할 · 스킬 원본 → Claude 링크 · Codex 표 생성 (단일 출처 유지).

원본 (세 곳, 뒤가 앞을 덮는다 — 역할 · 스킬은 이름이 같으면 프로젝트 것이 이긴다)
  .harness/core/{rules,agents,skills}                    코어 (모든 프로젝트 공통)
  .harness/core/packs/<pack>/{rules,agents,skills}       팩 (예: flutter)
  .harness/{rules,agents,skills}                          프로젝트

생성물 (직접 고치지 않는다)
  .claude/rules/<harness|pack|project>/<규칙>.md  → 원본 심볼릭 링크 (Claude 가 paths 로 골라 로드)
  .claude/agents/<역할>.md                         → 원본 심볼릭 링크
  .claude/skills/<스킬>/                           → 원본 심볼릭 링크
  AGENTS.md 의 <!-- harness:start --> ~ <!-- harness:end --> 블록 (Codex 가 읽는 규칙 · 스킬 · 역할 표)
"""
import os
import re
from pathlib import Path

import json

from lib import CORE, HARNESS, ROOT, front_matter, pack_dir

START = "<!-- harness:start"
END = "<!-- harness:end -->"
CLAUDE = ROOT / ".claude"


def _layers(cfg):
    pack = cfg.get("pack")
    layers = [("harness", CORE)]
    if pack:
        layers.append((pack, pack_dir(pack)))
    layers.append(("project", HARNESS))
    return layers


def rule_sources(cfg):
    """[(group, 원본 경로)]"""
    out = []
    for group, base in _layers(cfg):
        out += [(group, p) for p in sorted((base / "rules").glob("*.md"))]
    return out


def agent_sources(cfg):
    found = {}
    for _, base in _layers(cfg):
        for p in sorted((base / "agents").glob("*.md")):
            found[p.stem] = p
    return found


def skill_sources(cfg):
    found = {}
    for _, base in _layers(cfg):
        for p in sorted((base / "skills").glob("*/SKILL.md")):
            found[p.parent.name] = p.parent
    return found


def expected_links(cfg):
    """{링크 경로: 원본 경로}"""
    links = {}
    for group, src in rule_sources(cfg):
        links[CLAUDE / "rules" / group / src.name] = src
    for name, src in agent_sources(cfg).items():
        links[CLAUDE / "agents" / f"{name}.md"] = src
    for name, src in skill_sources(cfg).items():
        links[CLAUDE / "skills" / name] = src
    return links


def _rel(path):
    return os.path.relpath(path, ROOT)


def _existing_links():
    out = []
    for sub in ("rules", "agents", "skills"):
        base = CLAUDE / sub
        if base.is_symlink():
            out.append(base)
            continue
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            for n in dirnames + filenames:
                p = Path(dirpath) / n
                if p.is_symlink():
                    out.append(p)
    return out


def link_problems(cfg):
    problems = []
    expected = expected_links(cfg)
    for link, src in expected.items():
        if not link.is_symlink():
            problems.append(f"{_rel(link)} 링크가 없습니다 (원본: {_rel(src)})")
        elif link.resolve() != src.resolve():
            problems.append(f"{_rel(link)} 가 다른 곳을 가리킵니다 (원본: {_rel(src)})")
    for link in _existing_links():
        if link not in expected:
            problems.append(f"{_rel(link)} 는 원본이 없는 링크입니다")
    for sub in ("rules", "agents", "skills"):
        base = CLAUDE / sub
        if base.is_dir() and not base.is_symlink():
            for p in base.rglob("*"):
                if p.is_file() and not p.is_symlink() and not any(q.is_symlink() for q in p.parents):
                    problems.append(f"{_rel(p)} 는 사본입니다 — 원본은 .harness/{sub}/ 에 둔다")
    return problems


def apply_links(cfg):
    expected = expected_links(cfg)
    changed = []
    for link in _existing_links():
        if link not in expected or link.resolve() != expected[link].resolve():
            link.unlink()
            changed.append(f"- {_rel(link)}")
    for link, src in expected.items():
        if link.is_symlink():
            continue
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(os.path.relpath(src, link.parent))
        changed.append(f"+ {_rel(link)}")
    # 빈 폴더 정리 (원본이 사라진 팩 그룹 등)
    for base in (CLAUDE / "rules",):
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if d.is_dir() and not d.is_symlink() and not any(d.iterdir()):
                    d.rmdir()
    return changed


def _cell(text):
    return (text or "").replace("|", "\\|").strip()


def agents_block(cfg):
    always = set(cfg.get("always_loaded_rules", []))
    always_rows, path_rows = [], []
    for _, src in rule_sources(cfg):
        fields, paths = front_matter(src.read_text())
        link = f"[`{src.name}`]({_rel(src)})"
        if src.name in always and not paths:
            always_rows.append(f"- {link} — {_cell(fields.get('description'))}")
        else:
            targets = " · ".join(f"`{p}`" for p in paths) or "(paths 없음)"
            path_rows.append(f"| {link} | {targets} | {_cell(fields.get('description'))} |")
    skill_rows = []
    for name, src in skill_sources(cfg).items():
        fields, _ = front_matter((src / "SKILL.md").read_text())
        skill_rows.append(f"| [`{name}`]({_rel(src / 'SKILL.md')}) | {_cell(fields.get('description'))} |")
    agent_rows = []
    for name, src in agent_sources(cfg).items():
        fields, _ = front_matter(src.read_text())
        agent_rows.append(f"| [`{name}`]({_rel(src)}) | {_cell(fields.get('description'))} |")
    codex = (CORE / "templates/codex-rules.md").read_text().strip().splitlines()
    lines = [
        f"{START} — `.harness/core/harness sync` 가 생성한다. 이 블록은 직접 고치지 않는다 -->",
        *codex,
        "",
        "### 항상 읽는 규칙",
        "",
        *always_rows,
        "",
        "### 작업 대상별 규칙 — 해당할 때만 읽는다",
        "",
        "| 규칙 | 대상 (`paths`) | 내용 |",
        "|---|---|---|",
        *path_rows,
        "",
        "### 작업 절차 (스킬) — 해당하는 작업이면 시작할 때 읽고 절차대로 한다",
        "",
        "| 스킬 | 언제 |",
        "|---|---|",
        *skill_rows,
        "",
        "### 역할",
        "",
        "| 역할 | 하는 일 |",
        "|---|---|",
        *agent_rows,
        END,
    ]
    return "\n".join(lines)


BLOCK_RE = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)


def agents_md_problem(cfg):
    path = ROOT / "AGENTS.md"
    if not path.exists():
        return "AGENTS.md 가 없습니다 (`harness init`)"
    text = path.read_text()
    m = BLOCK_RE.search(text)
    if not m:
        return "AGENTS.md 에 harness 블록이 없습니다"
    if m.group(0) != agents_block(cfg):
        return "AGENTS.md 의 규칙 · 스킬 · 역할 표가 원본과 다릅니다"
    return None


def apply_agents_md(cfg):
    path = ROOT / "AGENTS.md"
    text = path.read_text()
    new = BLOCK_RE.sub(lambda _: agents_block(cfg), text) if BLOCK_RE.search(text) else text.rstrip() + "\n\n" + agents_block(cfg) + "\n"
    if new != text:
        path.write_text(new)
        return True
    return False


# ── .claude/settings.json 의 하네스 훅 ────────────────────
# init 은 settings 를 한 번만 복사한다. 하네스 업데이트로 훅이 늘거나 바뀌면 sync 가 하네스 항목만 템플릿에 맞춘다.
# 하네스 항목 = command 에 ".harness/core/scripts/hooks/" 가 든 것. 프로젝트가 추가한 훅 · 권한 · 다른 설정은 그대로 둔다.
SETTINGS = CLAUDE / "settings.json"
HOOK_MARK = ".harness/core/scripts/hooks/"


def _is_harness_entry(entry):
    return any(HOOK_MARK in (h.get("command") or "") for h in entry.get("hooks", []))


def desired_settings():
    template = json.loads((CORE / "templates/claude-settings.json").read_text())["hooks"]
    try:
        current = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        current = {}
    hooks = {k: [e for e in v if not _is_harness_entry(e)] for k, v in (current.get("hooks") or {}).items()}
    for event, entries in template.items():
        hooks[event] = hooks.get(event, []) + entries
    out = dict(current)
    out["hooks"] = {k: v for k, v in hooks.items() if v}
    return current, out


def settings_problem():
    if not SETTINGS.exists():
        return ".claude/settings.json 이 없습니다 (`harness init`)"
    current, desired = desired_settings()
    if current != desired:
        return ".claude/settings.json 의 하네스 훅이 이 하네스 버전과 다릅니다"
    return None


def apply_settings():
    current, desired = desired_settings()
    if current != desired:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(desired, ensure_ascii=False, indent=2) + "\n")
        return True
    return False
