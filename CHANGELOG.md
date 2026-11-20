# 변경 기록

프로젝트는 `.harness/core/harness update` 로 받을 때 이 파일의 변경을 보여 준다. 프로젝트에 영향이 있는 변경(설정 키 · 규칙 · 검사 · 차단 패턴)은 **영향**과 **할 일**을 함께 적는다.

## 0.1.0 — 2026-11-20

- 코어: 공통 규칙(`core.md`) · 역할(planner · reviewer) · 스킬(feature · bugfix · pr · feedback) · 검사(`check_rules` · `check_code`) · Claude 훅(실행 전 · 편집 직후 · 종료 전) · git 훅 · `harness` CLI(init · sync · verify · test · run · update · stats)
- Flutter 팩: 규칙(flutter · testing · platform) · 검사(print · 로그 속 인증 정보 · dart format · dart analyze) · 보호 패턴 · CI · 린트 템플릿 · `project-design` 스킬과 설계 선택지 카탈로그
