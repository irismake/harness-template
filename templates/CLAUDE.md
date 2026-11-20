# {{project_name}} — Claude Code

이 프로젝트는 **하네스**(`.harness/`)로 규칙 · 작업 절차 · 검증을 관리한다. Codex 와 같은 원본을 쓴다.

- 규칙은 `.claude/rules/` 링크로 자동 로드된다. `core.md` · `project.md` 는 항상, 나머지는 파일 맨 위 `paths` 에 맞는 파일을 읽을 때.
- 경로로 잡히지 않는 작업(예: 파일을 열기 전의 설계 질문)이면 [`AGENTS.md`](AGENTS.md) 표를 보고 해당 규칙을 직접 읽는다.
- **설계가 끝나지 않았으면**(`.harness/config.json` 의 `design_done: false`) 기능을 만들기 전에 `project-design` 스킬부터 한다.
- 훅(`.claude/settings.json`)이 위험 명령 · 보호 파일을 막고, 편집 직후 · 응답 종료 전에 검사한다.

## 프로젝트 전용 지침 (Claude)

없음. 생기면 여기에 적는다. 모든 에이전트에 공통인 규칙은 `.harness/rules/` 에 둔다.
