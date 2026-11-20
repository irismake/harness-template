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
| 프로젝트에 깔리는 파일 | `templates/` · `packs/<팩>/templates/` · `pack.json` `init_files` | init 은 있는 파일을 덮어쓰지 않는다 → 기존 프로젝트에는 CHANGELOG 로 안내 |

## 확인

```sh
python3 -m unittest discover -s tests -v     # 임시 프로젝트에 설치해 끝까지 돌린다 (Flutter 불필요)
bash tests/flutter_fixture.sh                 # 실제 Flutter 앱 fixture (flutter 필요)
```

PR 의 Template CI(`.github/workflows/test.yml`)가 둘 다 돌린다.

새 검사 · 패턴은 테스트에 "잡혀야 하는 것" 과 "잡히면 안 되는 것" 을 둘 다 넣는다.

## 릴리스

`main` 머지만으로는 프로젝트에 퍼지지 않는다. **태그 + release 브랜치**가 정식 릴리스다.

1. `main` 의 Template CI(`Test`)가 통과한 상태에서
2. `VERSION` 을 올리고 `CHANGELOG.md` 에 `## X.Y.Z — 날짜` 항목(변경 · 프로젝트가 할 일)을 쓴 커밋을 `main` 에 머지한다.
3. 그 커밋에 태그를 붙여 push 한다.

   ```sh
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

4. 릴리스 워크플로(`.github/workflows/release.yml`)가 확인한다: 태그 = `VERSION` · CHANGELOG 항목 · `main` 에 있는 커밋 · 현재 `release` 보다 새 커밋 · **Template CI 재실행 통과**. 모두 통과하면 `release` 브랜치를 그 커밋으로 옮긴다.
5. 각 프로젝트의 Dependabot 이 다음 확인 때 업데이트 PR 을 연다 → 프로젝트 CI → 사람이 머지.

실패하면 `release` 는 움직이지 않는다. 고친 뒤 태그를 지우고(`git push origin :refs/tags/vX.Y.Z`) 다시 붙이거나 다음 버전으로 낸다.

버전 규칙: 규칙 · 검사가 **더 엄격해져** 기존 프로젝트가 실패할 수 있으면 minor 이상, 문서 · 오탐 수정은 patch. 설정 키 · 규칙 파일 이름 변경처럼 프로젝트를 깨뜨리는 변경은 피하고, 꼭 필요하면 옛 이름도 한동안 읽게 한다.
