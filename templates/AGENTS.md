# {{project_name}} — 에이전트 지침 (Codex 등)

이 프로젝트는 **하네스**(`.harness/`)로 규칙 · 작업 절차 · 검증을 관리한다. Claude Code 와 같은 원본을 쓴다.
Codex 는 이 파일만 자동으로 읽으므로 아래 순서를 따른다.

1. 작업을 시작하기 전에 "항상 읽는 규칙" 두 개를 읽는다.
2. 작업 대상에 해당하는 규칙만 표에서 골라 추가로 읽는다. 해당하지 않는 규칙은 읽지 않는다.
3. 작업이 스킬 표에 해당하면 그 `SKILL.md` 를 읽고 절차대로 진행한다.
4. **설계가 끝나지 않았으면**(`.harness/config.json` 의 `design_done: false`) 기능을 만들기 전에 `project-design` 스킬부터 한다.

## 하네스 (자동 생성 — 하네스 버전에 맞춰 `harness sync` 가 다시 쓴다)

<!-- harness:start -->
<!-- harness:end -->

## 프로젝트 전용 지침 (Codex)

없음. 생기면 여기에 적는다. 모든 에이전트에 공통인 규칙은 `.harness/rules/` 에 둔다.
