# 하네스 템플릿 고치기

이 레포는 여러 프로젝트가 `.harness/core` 서브모듈로 공유한다. **여기 고친 것은 모든 프로젝트에 퍼진다** (각 프로젝트가 업데이트를 받을 때).

> 템플릿 루트에 `CLAUDE.md` · `AGENTS.md` 를 두지 않는다. 서브모듈 안에 있으면 프로젝트의 에이전트가 하위 폴더 지침으로 읽는다.

## 무엇을 어디에

| 바꿀 것 | 위치 | 기준 |
|---|---|---|
| 모든 언어 · 프로젝트 공통 규칙 | `rules/core.md` | 항상 로드된다 — 짧게. 경로로 나눌 수 있으면 팩 규칙으로 |
| 언어 · 프레임워크 규칙 | `packs/<팩>/rules/*.md` | frontmatter `description` · `paths` 필수 |
| 선택에 따라 달라지는 규칙 | `packs/<팩>/design/catalog.md` | 팩 규칙에 넣지 않는다 — 설계 때 프로젝트 규칙으로 생성 |
| 역할 · 스킬 | `agents/` · `skills/` · `packs/<팩>/skills/` | 이름 = 파일 · 폴더 이름 |
| 결정적 검사 | `scripts/check_code.py`(공통) · `packs/<팩>/checks.py` | 추가된 줄만 본다. 오탐이 없는지 실제 프로젝트에서 확인 |
| 차단 · 확인 패턴 | `scripts/lib.py` `DEFAULTS` · `packs/<팩>/pack.json` `protected` | 읽기 명령을 막지 않는지 (예: `grep fastlane`) |
| 프로젝트에 깔리는 파일 | `templates/` · `packs/<팩>/templates/` · `pack.json` `init_files` | init 은 있는 파일을 덮어쓰지 않는다 → 기존 프로젝트에는 PR 제목(→ CHANGELOG)으로 안내 |

## 기존 프로젝트를 깨뜨리지 않기

- **프로젝트가 이미 자체적으로 가지고 있을 수 있는 기능**(브랜치 정책 · TDD 강제 · 추가 검사 등)을 Core · Pack 에 넣을 때는 **기본값을 꺼 두고 `config.json` 으로 켠다** (opt-in). 새 프로젝트는 `project-design` · init 템플릿에서 켜고, 기존 프로젝트는 업데이트를 받아도 동작이 바뀌지 않는다.
- 이런 변경은 PR 제목 · 본문에 "새 옵션 — 쓰려면 `config.json` 에 …" 를 적는다 (CHANGELOG 가 된다).

## 확인

```sh
python3 -m unittest discover -s tests -v     # 임시 프로젝트에 설치해 끝까지 돌린다 (Flutter 불필요)
bash tests/flutter_fixture.sh                 # 실제 Flutter 앱 fixture (flutter 필요)
```

PR 의 Template CI(`.github/workflows/test.yml`)가 둘 다 돌린다.

새 검사 · 패턴은 테스트에 "잡혀야 하는 것" 과 "잡히면 안 되는 것" 을 둘 다 넣는다.

## 릴리스

**자동**이다. 사람이 하는 일은 PR 제목을 Conventional Commit 으로 쓰고 Squash 머지하는 것뿐이다.

1. PR 제목: `<type>: <요약>` — Squash 커밋 제목이 되고, 자동 릴리스가 이것으로 버전을 정한다. Template CI 가 형식을 검사한다.
   - `feat` → minor · `fix` `perf` `refactor` `ci` `build` `revert` → patch · `docs` `chore` `test` `style` → 릴리스 없음 · `!` / `BREAKING CHANGE` → major
   - 프로젝트가 직접 해야 할 일(설정 키 추가 · 템플릿 파일 변경 옮기기)이 있으면 PR 제목에 드러나게 쓴다 (CHANGELOG 가 제목으로 만들어진다).
2. Template CI 통과 → Squash 머지.
3. `main` push 의 Template CI 가 통과하면 `.github/workflows/release.yml` → `scripts/release.py` 가 지난 릴리스 이후 커밋을 분석해 `release` 브랜치에 릴리스 커밋(`VERSION` · `CHANGELOG.md`)과 태그를 만든다. `main` 은 건드리지 않는다.
4. 각 프로젝트의 Dependabot 이 업데이트 PR 을 연다 → 프로젝트 CI → 사람이 머지.

- 미리 보기: `python3 scripts/release.py --main origin/main --dry-run`
- 수동 릴리스(예: docs 만 바뀌었지만 내보내고 싶다): Actions → Release → Run workflow (`bump` 선택). Template CI 를 다시 돌린 뒤 릴리스한다.
- 버전 규칙: 규칙 · 검사가 **더 엄격해져** 기존 프로젝트가 실패할 수 있으면 `feat`(minor) 이상, 오탐 수정 · 문서는 `fix` · `docs`. 설정 키 · 규칙 파일 이름 변경처럼 프로젝트를 깨뜨리는 변경은 피하고, 꼭 필요하면 `!` 를 붙이고 옛 이름도 한동안 읽게 한다.
