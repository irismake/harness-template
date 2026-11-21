# 변경 기록

프로젝트는 `.harness/core/harness update` · Dependabot 업데이트 PR 로 받을 때 이 파일의 변경을 본다. 자동 릴리스가 커밋 제목으로 만든다.

## 0.5.0 — 2026-11-21

### 기능

- feat: 설정 값 리터럴 검사 (config-literal) — 코드 · 테스트가 같은 상수를 쓰게 한다 (#7)

## 0.4.2 — 2026-11-21

### 수정

- fix: TDD Guard 오탐 — 테스트 포맷 변경 · 같은 사이클 선언 파일을 RED → GREEN 으로 인정 (#6)

## 0.4.1 — 2026-11-21

### 수정

- fix: TDD Guard 우회 차단 — Bash 쓰기 감지 · RED 이후 구현 변경 확인 · 설계 골격 순서 (#5)

## 0.4.0 — 2026-11-21

### 기능

- feat: 에이전트 작업 자동 관리 — 작업 구간 · Mutation Guard · 판정 · 3라운드 · 토큰 실측 · 승격 PR · GitHub 지표 (#4)

## 0.3.0 — 2026-11-20

### 기능

- feat: TDD Guard · 요구사항 추적 — 테스트 먼저 강제, REQ → 시나리오 → 테스트 연결 검사 (#3)

## 0.2.0 — 2026-11-20

### 기능

- feat: 자동 릴리스 — 커밋 분석으로 VERSION · CHANGELOG · 태그 · release 브랜치 생성 (#2)

## 0.1.0 — 2026-11-20

- 코어: 공통 규칙(`core.md`) · 역할(planner · reviewer) · 스킬(feature · bugfix · pr · feedback) · 검사(`check_rules` · `check_code`) · Claude 훅(실행 전 · 편집 직후 · 종료 전) · git 훅 · `harness` CLI(init · sync · verify · test · run · update · stats)
- Flutter 팩: 규칙(flutter · testing · platform) · 검사(print · 로그 속 인증 정보 · dart format · dart analyze) · 보호 패턴 · CI · 린트 템플릿 · `project-design` 스킬과 설계 선택지 카탈로그
- 릴리스: `VERSION` · 태그 `vX.Y.Z` · `release` 브랜치(정식 릴리스만) · 릴리스 워크플로 · Template CI(회귀 · Flutter fixture · 업그레이드 호환성)
- 프로젝트: 서브모듈이 `release` 브랜치를 추적(`init` 이 `.gitmodules` 에 기록) · CI Harness job 이 PR 에서 `harness verify` · 두 job 모두 서브모듈 checkout · `harness update` 가 버전 변화 표시
