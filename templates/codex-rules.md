### 훅이 없는 도구(Codex)에서 지킬 것 — Claude 는 훅이 대신 한다

- 작업을 마치기 전에 `.harness/core/harness verify` 를 실행하고 통과시킨다. 빌드 · 전체 테스트는 로컬에서 돌리지 않는다 (CI).
- 커밋 · push 는 git 훅이 다시 검사한다. `--no-verify` 로 우회하지 않는다.
- `core.md` 의 "사용자 승인 없이 하지 않는다" 와 보호 파일을 스스로 지킨다. `.harness/core/` 는 고치지 않는다.
- 질문이 필요한 스킬(예: `project-design`)은 선택지를 번호 목록으로 보여 주고 답을 기다린다.
- 작업 규모를 `.harness/core/harness work lane <S|M|L>` 로 선언한다. 완료 조건(L: reviewer PASS · 리뷰 뒤 소스 불변 · 관련 테스트 통과 기록 / 모든 규모: verify 통과)은 push 때 git 훅이 확인한다.
- L 경로 계획: `.harness/core/harness work plan-start` → `planner` 형식대로 계획 파일에 쓰고 승인받는다. 독립 리뷰: 구현한 세션이 아니라 **새 세션**에서 `.harness/core/harness work review-start` 로 라운드 · 보고서 경로를 받고 `reviewer` 지침대로 한다 (최대 3라운드).
