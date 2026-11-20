---
description: 모든 프로젝트 공통 — 작업 범위 · 승인 필요 작업 · Secret · 작업 경로와 역할 · Git · 검증 · 규칙 관리 (하네스 코어, 항상 로드)
---

# 공통 규칙 (하네스 코어 · 항상 적용)

이 파일은 공유 하네스 `.harness/core/`(git 서브모듈)에 있다. **프로젝트에서 고치지 않는다.** 프로젝트 정보 · 결정은 `.harness/rules/project.md` · `.harness/rules/*.md` · `.harness/decisions/` 에 있다. 설정 값(브랜치 · 커밋 type · 명령 · 위험 영역)은 `.harness/config.json`.

## 시작

- `config.json` 의 `design_done` 이 `false` 면 기능을 만들기 전에 **`project-design` 스킬로 설계부터** 한다. 설계 없이 코드를 만들지 않는다.

## 작업 범위

- 요청받은 범위만 고친다. 관련 없는 리팩토링 · 포맷 변경 · 파일 이동을 섞지 않는다.
- 기존 구조 · 결정(`decisions/`)을 따른다. 결정에 없는 라이브러리 · 패턴을 들일 때는 먼저 묻는다. 결정을 바꾸면 결정 기록을 추가한다.
- **사용자 승인 없이 하지 않는다**: 커밋 · push · PR 생성 · 머지 · 배포 · 릴리스 · 패키지 추가 · 업그레이드 · 서명 · Secret · GitHub 설정 변경 · 하네스 업데이트.
- 키 · 인증서 · 서명 설정 · `.env` 를 커밋하지 않는다 (`git add -f` 금지). Secret · 토큰 값을 코드 · 로그 · 문서 · 커밋 · 메모리에 남기지 않는다. 키를 코드 · 문서에 붙여 넣었으면 지우는 것으로 끝내지 말고 사용자에게 알려 폐기 · 재발급하게 한다.

## 작업 경로 · 역할

메인 세션이 **오케스트레이터 겸 구현자**다 (대화 · 경로 판정 · 승인 받기 · 구현 · 테스트). 보조 역할은 **planner** · **reviewer** 둘뿐이고 역할마다 에이전트 하나만 쓴다. 같은 일을 여러 에이전트 · 모델로 중복 실행하지 않는다.

| 경로 | 기준 | 흐름 |
|---|---|---|
| S | 문구 · 스타일 · 한 파일의 단순 수정 | 바로 구현 |
| M | 한 계층 · 한 기능 안의 기능 · 버그 | 계획을 몇 줄로 공유 → 구현 |
| L | 여러 계층에 걸침, 또는 위험 영역(`config.json` `risk_areas` · 인증 · 네트워크 공통 · DI · 플랫폼 설정 · CI/CD · 서버 계약 · 동시성 · 결제) | planner → **사용자 승인** → 구현 → reviewer → 지적 반영 → 재검토는 1회까지 |

- 애매하면 한 단계 위 경로를 고른다. 사용자가 요청하면 경로와 관계없이 planner · reviewer 를 쓴다.
- reviewer 에게는 요구사항과 비교 기준 ref 만 넘긴다. 구현 과정 설명을 넘기지 않는다 (독립성).
- reviewer 지적은 하나씩 "반영 / 반영 안 함(이유)" 으로 정리해 사용자에게 보고한다.
- 사용자가 실수를 지적했거나, 같은 유형의 문제가 다시 나왔거나, 규칙이 실제 코드와 다르면 `feedback` 스킬로 재발 방지 수단까지 반영한다.

## Git

- 브랜치: `config.json` `branch_prefixes` 중 하나 + `/` + kebab-case (예: `feat/login`). `base_branch` 에서 분기한다. 보호 브랜치(`protected_branches`)에 직접 커밋 · push 하지 않는다.
- 커밋 메시지: `<type>: <요약>` (`commit_types`). git 훅이 검사한다.
- 머지 방식 · 브랜치 전략은 `project.md` "브랜치 · 머지".

## 작업 절차 · 검증

- 반복 작업은 스킬을 따른다: `project-design`(설계) · `feature`(기능 · 리팩토링, TDD) · `bugfix`(재현 테스트 먼저) · `pr`(커밋 · PR, 요청 시만) · `feedback`(실수 → 재발 방지).
- 테스트는 `.harness/core/harness test <파일|폴더>` 로 **관련 테스트만** 실행한다. TDD 단계(RED · GREEN)에서는 사용자 요청 없이 실행한다. `config.json` `tdd.enabled` 면 TDD Guard 가 RED 기록 없는 기능 코드 수정 · 완료를 막는다 (`feature` 스킬). `trace.enabled` 면 요구사항(REQ) → 시나리오(TS) → 테스트를 문서와 테스트에 ID 로 연결한다 (`harness trace`).
- 작업을 마치기 전에 `.harness/core/harness verify` (하네스 구성 · 코드 규칙 · 포맷 · 정적 분석, 수 초) 를 통과시킨다. Claude 는 훅이 자동으로 검사한다.
- **로컬 검증에 전체 테스트 · 릴리스 빌드를 넣지 않는다** (오래 걸린다). CI 가 맡는다. 사용자가 요청할 때만 로컬에서 실행한다.
- 실행하지 않은 검증은 결과를 보고하지 않는다 ("빌드 성공" · "테스트 통과" 등). 실행 결과만 근거로 쓴다.

## 규칙 관리

- 원본은 세 곳뿐이다: 코어 `.harness/core/rules/` · 팩 `.harness/core/packs/<팩>/rules/` (둘 다 템플릿 레포에서만 고친다) · 프로젝트 `.harness/rules/`. `.claude/` 링크와 `AGENTS.md` 표는 `harness sync` 가 만든다. 사본을 만들지 않는다.
- 프로젝트 규칙을 추가 · 삭제 · 이름 변경하면 frontmatter(`description` · `paths`)를 쓰고 `.harness/core/harness sync` 를 실행한다.
- 프로젝트 규칙 · 결정은 에이전트 개인 메모리가 아니라 `.harness/` 에 적는다 (개인 메모리는 다른 에이전트 · 사람이 못 읽는다).
- 코드에서 알 수 있는 내용은 규칙에 옮겨 적지 않고 위치만 가리킨다. 모든 프로젝트에 해당하는 개선은 템플릿 레포(irismake/harness-template)에 제안한다.
