---
description: Dart · Flutter 공통 — 포맷 · 정적 분석 · 생성 파일 · 로깅 · null 안전 · 위젯 · 비동기 · 테마 · 의존성 · 비밀 값
paths:
  - "**/*.dart"
  - "pubspec.yaml"
  - "analysis_options.yaml"
---

# Dart · Flutter 공통 (Flutter 팩)

상태 관리 · 폴더 구조 · 라우팅 · 데이터 계층처럼 **프로젝트가 고른 것**은 `.harness/rules/` 의 프로젝트 규칙을 따른다. 이 파일은 어떤 선택에도 해당하는 것만 둔다.

## 포맷 · 분석

- `dart format` 결과를 그대로 쓴다. `flutter analyze` 는 경고 · info 포함 0건을 유지한다 (CI 와 같다).
- `analysis_options.yaml` 의 규칙을 끄거나 `// ignore:` 를 넣으려면 이유를 적고 사용자 승인을 받는다.
- 생성 파일(`*.g.dart` · `*.freezed.dart` · `*.gr.dart` · `*.config.dart` · `*.mocks.dart`)은 직접 고치지 않는다. 원본을 고치고 `.harness/core/harness run codegen`.

## 설정 값

- 타임아웃 · 재시도 횟수 · 크기 제한 같은 고정 설정 값은 상수 한 곳(예: `lib/core/constants/<영역>_constants.dart`)에 두고, 코드 · 테스트가 같은 상수를 쓴다. 코드에 `Duration(...)` 같은 값을 직접 넣지 않는다. (검사: `config-literal`, `config.json` `config_literals.enabled` 로 켠다)

## 로깅 · 오류

- `print` · `debugPrint` 를 쓰지 않는다. 프로젝트 로거(`project.md` 결정)를 쓴다. (검사: `logging`)
- 토큰 · 비밀번호 · 쿠키 · 개인정보를 로그 · 오류 메시지 · 분석 이벤트에 넣지 않는다. 있음/없음 · 길이 같은 상태만 남긴다. (검사: `sensitive-log`)
- 예외를 삼키지 않는다 (`catch (_) {}` 금지). 처리하지 못하면 로그를 남기고 상위로 올리거나 사용자에게 보여 줄 오류 상태로 바꾼다.

## 언어

- null 안전: `!` 는 바로 위에서 null 이 아님을 보장할 때만. `late` 는 초기화 시점이 확실할 때만.
- 공개 API 와 모델은 불변(`final` 필드 · `const` 생성자)으로 만든다. 컬렉션을 밖으로 내보낼 때 수정 가능한 원본을 그대로 넘기지 않는다.
- `dynamic` 을 피한다. JSON 은 경계(데이터 계층)에서 바로 타입으로 바꾼다.
- 비동기: `Future` 를 버리지 않는다 (`await` 하거나 `unawaited(...)` 로 의도를 밝힌다). `await` 뒤에 `BuildContext` 를 쓰면 먼저 `mounted`(`context.mounted`)를 확인한다.

## 위젯

- `build` 에서 부수 효과(요청 · 저장 · 네비게이션 · 상태 변경)를 일으키지 않는다.
- 커지는 `build` 는 **위젯 클래스**로 나눈다 (위젯을 반환하는 private 메서드보다 우선). 바뀌지 않는 위젯은 `const`.
- 색 · 글꼴 · 간격은 테마(`Theme.of(context)` · 프로젝트 디자인 토큰)를 쓴다. 하드코딩 색 · `TextStyle(fontSize: …)` 를 새로 만들지 않는다. 필요한 토큰이 없으면 **먼저 묻는다**.
- 사용자에게 보이는 문자열은 다국어 결정(`project.md`)을 따른다.
- 리스트는 길이가 정해지지 않으면 `ListView.builder` 같은 지연 생성을 쓴다.

## 의존성 · 비밀 값

- 패키지 추가 · 삭제 · 메이저 업그레이드는 사용자 승인 후에만 한다. 추가할 때는 유지 상태(최근 릴리스 · pub 점수)와 이유를 함께 제안한다.
- 앱에 넣는 키는 공개된다고 가정한다. 서버 비밀 키를 앱에 넣지 않는다.
- 환경 값은 `--dart-define-from-file=env/<환경>.json` 으로 넣고 `env/*.json` 은 커밋하지 않는다. 예시는 `env/<환경>.example.json`. (검사: `secret-file`)
