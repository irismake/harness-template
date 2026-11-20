#!/usr/bin/env python3
"""
하네스 구성 검사 (단일 출처 · 진입점 · 서브모듈). 문제가 있으면 목록을 출력하고 exit 1.

사용: python3 .harness/core/scripts/check_rules.py   (또는 .harness/core/harness check-rules)

  1. .harness/config.json 이 있고 팩이 존재한다
  2. .claude/{rules,agents,skills} 링크가 원본과 일치한다 — 빠진 링크 · 끊긴 링크 · 사본 없음
  3. 다른 도구용 규칙 사본(.codex/rules · .cursor · .cursorrules)이 없다
  4. 규칙: description 이 있다. paths 없는 규칙은 always_loaded_rules 에 든 것만.
     프로젝트 규칙의 paths 는 실제 파일에 하나 이상 맞는다 (경로 변경 감지)
  5. 역할: name(=파일명) · description · tools / 스킬: name(=폴더명) · description
  6. AGENTS.md 표가 원본에서 생성한 것과 같다 / CLAUDE.md 가 있다
  7. 공유 하네스(.harness/core)를 프로젝트 안에서 고치지 않았다
고치는 방법: 대부분 `.harness/core/harness sync`
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import events  # noqa: E402
import sync  # noqa: E402
from lib import CONFIG_PATH, CORE, HARNESS, ROOT, front_matter, git, glob_regex, load_config, pack_dir, tracked_files  # noqa: E402

FORBIDDEN_COPIES = [".codex/rules", ".cursor", ".cursorrules", "CURSOR.md"]


def main():
    problems = []
    if not CONFIG_PATH.exists():
        print("하네스가 초기화되지 않았습니다: .harness/core/harness init <팩>")
        sys.exit(1)
    cfg = load_config()
    pack = cfg.get("pack")
    if pack and not (pack_dir(pack) / "pack.json").exists():
        problems.append(f"config.json 의 팩 '{pack}' 이 .harness/core/packs/ 에 없습니다")

    problems += sync.link_problems(cfg)
    for p in FORBIDDEN_COPIES:
        if (ROOT / p).exists():
            problems.append(f"규칙 사본이 있습니다: {p} — 원본은 .harness/rules/ 하나만 둔다")

    tracked = tracked_files()
    always = set(cfg.get("always_loaded_rules", []))
    rules = sync.rule_sources(cfg)
    for group, src in rules:
        fields, paths = front_matter(src.read_text())
        label = f"{group}/{src.name}"
        if not fields.get("description"):
            problems.append(f"규칙 {label}: frontmatter 에 description 이 없습니다")
        if not paths:
            if src.name not in always:
                problems.append(f"규칙 {label}: paths 가 없습니다 (항상 로드할 내용은 project.md 에 둔다)")
            continue
        if src.name in always:
            problems.append(f"규칙 {label}: 항상 로드되는 규칙에 paths 가 있습니다")
        if group == "project":
            for pattern in paths:
                if not any(glob_regex(pattern).match(f) for f in tracked):
                    problems.append(f"규칙 {label}: paths '{pattern}' 에 맞는 파일이 없습니다")

    for name, src in sync.agent_sources(cfg).items():
        fields, _ = front_matter(src.read_text())
        for key in ("name", "description", "tools"):
            if key not in fields:
                problems.append(f"역할 {name}: frontmatter 에 {key} 가 없습니다")
        if fields.get("name") and fields["name"] != name:
            problems.append(f"역할 {name}: name 이 파일명과 다릅니다 ({fields['name']})")
    skills = sync.skill_sources(cfg)
    for name, src in skills.items():
        fields, _ = front_matter((src / "SKILL.md").read_text())
        for key in ("name", "description"):
            if key not in fields:
                problems.append(f"스킬 {name}: frontmatter 에 {key} 가 없습니다")
        if fields.get("name") and fields["name"] != name:
            problems.append(f"스킬 {name}: name 이 폴더명과 다릅니다 ({fields['name']})")

    if p := sync.agents_md_problem(cfg):
        problems.append(p)
    if not (ROOT / "CLAUDE.md").exists():
        problems.append("CLAUDE.md 가 없습니다 (`harness init`)")

    if CORE.parent == HARNESS and (CORE / ".git").exists():
        dirty = git("status", "--porcelain", cwd=CORE, check=False).strip()
        if dirty:
            problems.append("공유 하네스(.harness/core)가 프로젝트 안에서 수정됐습니다 — 되돌리고 템플릿 레포에서 고친다:\n"
                            + "\n".join(f"      {l}" for l in dirty.splitlines()[:10]))

    events.record("fail" if problems else "pass", check="rules", rules=["harness-sync"] * len(problems))
    if problems:
        print("하네스 구성 검사 실패 (대부분 `.harness/core/harness sync` 로 고친다):")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print(f"하네스 구성 검사 통과: 팩 {pack or '없음'} · 규칙 {len(rules)}개 · 역할 {len(sync.agent_sources(cfg))}개 · 스킬 {len(skills)}개")


if __name__ == "__main__":
    main()
