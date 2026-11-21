---
name: pr
description: 작업을 커밋하고 PR 을 만든다. 사용자가 커밋 · PR 을 요청했을 때만 사용. 머지 · 배포는 하지 않는다.
---

# 커밋 · PR

## 실행 조건

사용자가 커밋 또는 PR 을 **명시적으로 요청**했을 때만. 머지 · 자동 머지 설정 · 배포는 이 스킬의 범위가 아니다 (`core.md`).

## 절차

1. **브랜치 확인**: 보호 브랜치(`protected_branches`)면 `core.md` 이름 규칙으로 새 브랜치를 만든다.
2. **변경 확인**: `git status` · `git diff` 로 의도한 파일만 들어가는지 본다. Secret · 서명 파일 · 개인 설정(`.claude/settings.local.json`) · 빌드 산출물은 넣지 않는다. `.harness/core` 포인터가 바뀌었으면 의도한 하네스 업데이트인지 확인한다.
3. **검증**: `.harness/core/harness verify` 통과. 커밋 시 git 훅이 다시 검사한다 (`--no-verify` 금지).
4. **커밋**: `<type>: <요약>`. 기능 단위로 나눈다.
5. **PR 대상**: `base_branch`. hotfix · 승격은 `project.md` "브랜치 · 머지" 를 따른다.
6. **PR 본문**

   ```
   ## 변경 사항
   - <무엇을 왜>
   (버그면: 증상 · 원인 · 수정)

   ## 테스트
   - <실제로 실행한 명령과 결과. 실행하지 않았으면 그렇게 적는다>
   ```

   UI 변경이면 스크린샷을 첨부해 달라고 사용자에게 알린다.
7. push 후 PR URL 을 보고한다. CI 결과를 기다리거나 머지하지 않는다.

## 승격 PR (예: `dev → staging` · `staging → main`)

사용자가 **승격 PR 을 명시적으로 요청**했을 때만. PR 생성과 머지는 다른 권한이다 — 머지는 하지 않는다 (훅이 `gh pr merge` 를 막는다).

1. `.harness/core/harness pr check-promotion <head> <base>` — 모두 통과해야 다음 단계로 간다.
   - 승격 경로가 프로젝트 브랜치 전략(`config.json` `promotion`, 예: `[["dev","staging"],["staging","main"]]`)에 있다
   - 원격 `head` · `base` 가 있고, `head` 에 `base` 에 없는 커밋이 있다 (빈 diff 가 아니다)
   - 같은 `head → base` 로 열린 PR 이 없다 (있으면 그 PR 을 보고하고 끝낸다)
   - `head` 최신 커밋의 필수 검사가 모두 성공했다
2. 추가 push 가 필요하면 멈추고 보고한다 (사용자가 따로 요청하지 않은 push 는 하지 않는다).
3. PR 본문: 목적 · `base...head` 커밋 · 변경 요약 · 검사 결과 · 미검증 · 확인할 것 (배포 영향).
4. PR URL 을 보고한다. 머지 방식(merge commit · squash)은 `project.md` "브랜치 · 머지" 를 따르라고 사용자에게 알린다.

## 완료 조건

- 의도한 변경만 커밋됐다.
- PR 본문의 "테스트" 가 실제 실행 결과와 일치한다.
- 머지를 하지 않았다.
