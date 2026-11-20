---
name: project-design
description: 새 Flutter 앱의 설계부터 시작한다 — 무엇을 만들지 듣고, 상태 관리 · 폴더 구조 · 라우팅 · 데이터 · 브랜치 등을 선택지로 물어 사용자가 고르게 한 뒤, 결정 기록 · 프로젝트 규칙 · 설정 · 앱 골격을 만든다. config.json 의 design_done 이 false 이거나, 사용자가 "앱을 만들고 싶다" · "설계부터" · "구조를 다시 정하자" 고 할 때 사용.
---

# 프로젝트 설계 (Flutter)

목표: 이 스킬이 끝나면 **에이전트가 규칙을 보고 바로 첫 기능을 TDD 로 만들 수 있는 상태**가 된다.
선택지 · 추천 · 고른 뒤 만들 것은 [`../../design/catalog.md`](../../design/catalog.md) 에 있다. 먼저 읽는다.

## 원칙

- **결정은 사용자가 한다.** 에이전트는 선택지 2~4개와 추천(이유 한 줄)을 제시한다. 사용자가 모르겠다고 하면 추천을 쓰고 그렇게 기록한다.
- 이미 답한 것은 다시 묻지 않는다 (요청 문장 · 앞 단계 답에서 알 수 있으면 확인만).
- 앞 단계 답에 따라 추천을 바꾼다 (예: 백엔드가 Firebase 면 네트워크 질문 생략, 오프라인 우선이면 drift 추천).
- 질문 도구
  - **Claude**: `AskUserQuestion` — 한 번에 질문 최대 4개, 선택지 2~4개, 추천을 첫 선택지로 두고 라벨 끝에 "(추천)". 플랫폼처럼 여러 개를 고르는 것은 `multiSelect`.
  - **Codex 등 질문 도구가 없을 때**: 질문마다 번호 목록(추천 표시)으로 보여 주고 답을 기다린다. 한 번에 4개 이내.
- 파일 · 패키지 · 명령은 **6단계 승인 전에는 만들지 않는다** (읽기만).

## 절차

### 0. 상태 확인

- `.harness/config.json` (`design_done`) · `pubspec.yaml` · `lib/` · `.harness/decisions/` 를 본다.
  - 설계 완료 + 앱 있음: 무엇을 다시 정할지 묻고 해당 주제만 진행한다 (새 결정 기록 `NNNN-<주제>.md`, 기존 기록은 "대체됨").
  - **기존 Flutter 앱에 하네스를 막 설치한 경우**: 질문하기 전에 `pubspec.yaml` · `lib/` 구조 · `analysis_options.yaml` 을 읽어 현재 선택을 추정하고 "지금 이렇게 되어 있다 — 그대로 기록할까, 바꿀까" 로 확인한다. 골격 생성(7단계)은 건너뛴다.
- `flutter --version` (fvm 이 있으면 `fvm list` 도)으로 쓸 수 있는 Flutter 버전을 확인한다.

### 1. 무엇을 만드나 (자유 서술)

요청에 없는 것만 한 메시지로 묻는다.
- 앱 이름 (표시 이름 · 패키지 이름 `snake_case`) · 조직 ID(번들 ID 앞부분, 예: `com.example`)
- 한 줄 설명 · 주요 사용자 · 핵심 기능 3~7개 · 참고하는 앱 · 출시 목표 시점

답을 받으면 **도메인 용어**(코드에서 쓸 영어 이름 ↔ 뜻)와 **기능 목록** 초안을 만든다.

### 2. 제품 범위 (질문 1회) — 카탈로그 A

플랫폼 · 백엔드 · 로그인 · 오프라인.

### 3. 아키텍처 (질문 1회) — 카탈로그 B

상태 관리 · 폴더 구조 · 라우팅 · 모델/직렬화.

### 4. 데이터 · 인프라 (질문 1~2회) — 카탈로그 C

네트워크(자체 서버일 때) · 로컬 저장 · 다국어 · 디자인/테마 · 환경 분리 · 로깅. 해당 없는 것은 묻지 않는다.

### 5. 개발 방식 (질문 1회) — 카탈로그 D

브랜치 · Flutter 버전 관리 · 테스트 정책 · 목 도구 · CI 범위.

### 6. 설계안 확인 (승인)

아래를 한 번에 보여 주고 **"이대로 만들까요?"** 승인을 받는다. 수정 요청이 있으면 해당 부분만 다시 묻는다.
- 결정 표 (주제 · 선택 · 이유)
- 폴더 구조 트리
- 설치할 패키지 목록 (dependencies / dev_dependencies)
- 만들 파일 목록 (결정 기록 · 규칙 · 설정 · 골격)
- 기능 목록과 추천 구현 순서

### 7. 만들기 (승인 후)

순서대로 하고, 실패하면 멈추고 보고한다.

1. **결정 기록**: `.harness/decisions/0001-initial-design.md` (`decisions/README.md` 형식 — 모든 주제의 선택 · 대안 · 이유).
2. **앱 골격** (기존 앱이면 건너뜀)
   - fvm 을 골랐으면 `fvm use <버전> --force` → `.fvmrc`. 이후 `flutter` · `dart` 명령은 `fvm` 을 붙인다.
   - `flutter create --org <조직 ID> --project-name <패키지 이름> --platforms <고른 플랫폼> .`
   - `analysis_options.yaml` 을 `.harness/core/packs/flutter/templates/analysis_options.yaml` 내용으로 바꾼다.
   - 패키지: `flutter pub add <패키지들>` · `flutter pub add --dev <패키지들>` (6단계에서 승인한 목록만. Claude 는 훅이 확인 창을 띄운다).
   - 폴더 구조 · 앱 시작 코드(`main.dart` · `app.dart`) · 라우터 · 테마 · 로거 · (백엔드가 있으면) 네트워크 클라이언트 · 오류 타입 · 환경 값 읽기를 **최소한으로** 만든다. 기능 화면은 만들지 않는다 (첫 화면 하나만 자리 표시).
   - `.gitignore` 는 `harness init` 이 Flutter 기본 항목 · `env/*.json` 까지 넣어 두었다 (`flutter create` 는 있는 `.gitignore` 를 덮어쓰지 않는다). 빠진 것만 더한다.
   - 환경 분리를 골랐으면 `env/dev.example.json` · `env/prod.example.json` 을 만든다 (실제 값 파일 `env/<환경>.json` 은 사용자가 만든다).
   - 생성 파일을 커밋하지 않기로 했으면 `.gitignore` 에 `*.g.dart` · `*.freezed.dart` 등을 넣는다.
   - 스모크 테스트 `test/app_test.dart` (앱이 첫 화면을 그린다) — 프로젝트 테스트 구조의 예시가 된다.
   - `flutter create` 가 만든 기본 카운터 예제 코드 · 테스트는 지운다.
3. **프로젝트 규칙** (`.harness/rules/`, frontmatter `description` · `paths` 필수)
   - `project.md` 를 채운다 (템플릿의 "설계 전" 문구는 지운다, 60줄 이내).
   - `architecture.md` (`paths: ["lib/**"]`) · 필요하면 `data.md` — 카탈로그의 "규칙에 쓸 것" 중 **고른 것만**, 실제로 만든 폴더 · 파일 이름으로 쓴다. 코드에서 알 수 있는 것은 옮겨 적지 않고 위치를 가리킨다.
4. **설정** (`.harness/config.json`): `design_done: true` · `base_branch` · `protected_branches` · `layers`(카탈로그 B2) · `risk_areas`(네트워크 · 인증 · 결제 폴더).
5. **CI**: `.github/workflows/ci.yml` 의 `push.branches` 를 보호 브랜치에 맞춘다. 빌드 확인을 골랐으면 Android(`flutter build apk --debug`) · iOS(`macos` 러너, `flutter build ios --no-codesign`) job 을 추가한다.
6. **동기화 · 확인**
   - `.harness/core/harness sync`
   - `flutter pub get` (+ build_runner 를 쓰면 `.harness/core/harness run codegen`)
   - `.harness/core/harness test test/app_test.dart`
   - `.harness/core/harness run analyze`
   - `.harness/core/harness verify`
   - 일부러 계층 위반 import 를 한 줄 넣어 `layer` 검사가 잡는지 확인하고 되돌린다 (`layers` 를 만들었을 때).

### 8. 보고 · 다음 단계

- 만든 파일 · 설치한 패키지(버전) · 실행한 확인과 결과 (실행하지 않은 것은 그렇다고)
- 커밋 제안: `chore: 프로젝트 설계 · 앱 골격` (커밋은 사용자가 요청할 때 `pr` 스킬로)
- GitHub 레포가 있으면: 브랜치 보호에서 `Harness` · `Flutter` job 을 Required check 로 지정하라고 안내한다 (에이전트가 설정하지 않는다).
- 기능 목록의 첫 기능을 제안한다 → 사용자가 고르면 `feature` 스킬로 시작.

## 완료 조건

- 모든 주제에 사용자가 고른(또는 추천을 받아들인) 선택이 결정 기록에 이유와 함께 있다.
- `project.md` 가 채워졌고 `config.json` `design_done` 이 `true` 다.
- (새 앱) 스모크 테스트 · 정적 분석 · `verify` 를 실제로 실행해 통과했다.
