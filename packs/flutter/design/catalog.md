# Flutter 설계 선택지 카탈로그

`project-design` 스킬이 질문에 쓰는 선택지와, 고른 뒤 만들 규칙 · 설정이다.
**추천은 출발점일 뿐이다.** 앞 단계 답(백엔드 · 규모 · 오프라인)에 따라 추천을 바꾸고, 바꾼 이유를 선택지 설명에 적는다.
패키지 버전은 적지 않는다 — 설치할 때 `flutter pub add` 로 최신 안정 버전을 받고, 유지 상태(최근 릴리스 · pub 점수)를 확인해 보고한다.

---

## A. 제품 범위

| 주제 | 선택지 | 메모 |
|---|---|---|
| 플랫폼 (복수) | iOS · Android · Web · macOS/Windows | 고른 것만 `flutter create --platforms` |
| 백엔드 | ① 자체 REST/GraphQL 서버 ② Firebase ③ Supabase ④ 없음 (기기 안에서만) | ②③이면 네트워크 클라이언트 질문을 줄인다 |
| 로그인 | ① 없음 ② 이메일 · 비밀번호 ③ 소셜(Apple · Google · Kakao …) ④ 백엔드 SDK 인증 | iOS 에서 소셜 로그인을 넣으면 Apple 로그인이 필요할 수 있다고 알린다 |
| 오프라인 | ① 온라인 전용 ② 최근 데이터 캐시 ③ 오프라인 우선(동기화) | ③이면 로컬 DB(drift) 추천 |

## B. 아키텍처

### B1. 상태 관리

| 선택지 | 언제 | 패키지 |
|---|---|---|
| **Riverpod (추천)** | 대부분. DI 를 겸하고 테스트에서 override 가 쉽다 | `flutter_riverpod` (+ 코드 생성을 쓰면 `riverpod_annotation` · dev `riverpod_generator` · `build_runner`) |
| Bloc / Cubit | 이벤트 → 상태 흐름을 엄격히 남기고 싶을 때, 팀이 Bloc 에 익숙할 때 | `flutter_bloc` (+ dev `bloc_test`) · DI 는 `get_it` 또는 `RepositoryProvider` |
| Provider + ChangeNotifier | 아주 작은 앱 · 학습용 | `provider` |

규칙에 쓸 것
- Riverpod: 상태 · 비동기 로직은 `Notifier`/`AsyncNotifier`, 위젯은 `ref.watch` 로 읽고 이벤트에서 `ref.read(...notifier)` 로 부른다. `build` 안에서 `ref.read` 로 상태를 읽지 않는다. 화면 상태는 `AsyncValue` 로 로딩 · 오류 · 데이터를 모두 그린다. 저장소 · 클라이언트도 provider 로 노출하고 테스트에서 `ProviderContainer(overrides: …)` 로 바꾼다. 코드 생성 사용 여부를 한 가지로 통일한다.
- Bloc: 화면마다 Bloc/Cubit 하나, 상태는 불변 클래스(sealed 또는 freezed). UI 는 `BlocBuilder`/`BlocSelector`, 부수 효과는 `BlocListener`. Bloc 끼리 직접 참조하지 않는다 (저장소 스트림으로 연결). 테스트는 `bloc_test`.
- Provider: `ChangeNotifier` 는 화면 로직만, 데이터 접근은 저장소에. `notifyListeners` 를 `build` 중에 부르지 않는다.

### B2. 폴더 구조 · 계층

| 선택지 | 언제 |
|---|---|
| **기능 우선 + 계층 (추천)** | 기능이 3개 이상 · 오래 유지할 앱 |
| 계층 우선 | 기능이 적고 화면 간 공유가 많을 때 |
| 단순 기능 폴더 (계층 없음) | 프로토타입 · 해커톤 |

기능 우선 + 계층
```
lib/
  main.dart · app.dart            앱 시작 · MaterialApp(router · theme)
  core/                           여러 기능이 쓰는 것: network · storage · logging · theme · router · error · utils
  features/<기능>/
    domain/                       엔티티 · 저장소 인터페이스 · (필요하면) 유스케이스 — Flutter UI · data 를 모른다
    data/                         DTO · 원격/로컬 데이터 소스 · 저장소 구현 — DTO 는 여기서 엔티티로 바꿔 내보낸다
    presentation/                 화면 · 위젯 · 상태(노티파이어/블록)
test/ 는 lib/ 구조를 그대로
```
config `layers` (결정적 검사):
```json
[
  {"files": "lib/features/**/domain/**", "forbid": ["package:flutter/material.dart", "package:flutter/widgets.dart", "package:flutter/cupertino.dart", "package:material_ui/", "package:cupertino_ui/", "/data/", "/presentation/"],
   "message": "domain 은 UI · data · presentation 을 참조하지 않는다", "rule": ".harness/rules/architecture.md"},
  {"files": "lib/features/**/presentation/**", "forbid": ["/data/"],
   "message": "presentation 은 data 를 직접 참조하지 않는다 (domain · 상태를 거친다)", "rule": ".harness/rules/architecture.md"},
  {"files": "lib/core/**", "forbid": ["/features/"],
   "message": "core 는 특정 기능을 참조하지 않는다", "rule": ".harness/rules/architecture.md"}
]
```
(백엔드 클라이언트 패키지 — 예: `package:dio/` — 를 domain · presentation 금지 목록에 더한다.
Flutter 3.50 부터 Material 은 `package:material_ui/material_ui.dart` 로 옮겨졌다 — `flutter create` 가 만든 `lib/main.dart` 의 import 를 따르고, UI 금지 목록에는 옛 경로 · 새 경로를 둘 다 둔다)

계층 우선: `lib/{core, data/{dto,sources,repositories}, domain/{entities,repositories}, presentation/<화면>/}` — layers 는 같은 원리로 `lib/domain/**` · `lib/presentation/**` 에 건다.

단순 기능 폴더: `lib/features/<기능>/{<기능>_screen.dart, <기능>_controller.dart, <기능>_repository.dart}` — layers 없음, `architecture.md` 에 "기능 3개를 넘으면 계층 구조로 옮길지 묻는다" 를 적는다.

유스케이스 계층은 기본으로 만들지 않는다 — 여러 저장소를 조합하거나 규칙이 복잡한 로직만 `domain/usecases/` 에 둔다 (빈 전달 클래스 금지).

### B3. 라우팅

| 선택지 | 메모 |
|---|---|
| **go_router (추천)** | Flutter 팀 관리. 딥링크 · 웹 URL · 로그인 리다이렉트 · `ShellRoute`(탭) |
| auto_route | 코드 생성으로 타입 안전한 경로 인자 |
| Navigator 직접 | 화면 2~3개짜리만 |

규칙: 경로 상수 · 라우터 설정은 `core/router/` 한 곳. 화면 간 전달은 id 같은 작은 값만 (객체 전체를 넘기지 않는다). 로그인 리다이렉트는 라우터 `redirect` 에서.

### B4. 모델 · 직렬화

| 선택지 | 메모 |
|---|---|
| **freezed + json_serializable (추천)** | 불변 · `copyWith` · sealed union · JSON 생성. dev `build_runner` |
| json_serializable 만 | 불변 · `copyWith` 는 직접 |
| 수동 | 모델이 매우 적을 때 |

규칙: DTO(서버 모양, `data/`)와 엔티티(앱이 쓰는 모양, `domain/`)를 나눈다. DTO 필드 이름 · nullable 은 서버 스펙과 같게, 엔티티는 앱이 실제로 쓰는 필드만. 변환은 DTO 의 `toEntity()`. 생성 파일 커밋 여부를 정한다 (추천: 커밋하지 않고 CI 에서 생성 → `.gitignore` 에 `*.g.dart` · `*.freezed.dart`).

## C. 데이터 · 인프라

### C1. 네트워크 (백엔드가 ① 자체 서버일 때)

| 선택지 | 메모 |
|---|---|
| **dio (추천)** | 인터셉터(인증 헤더 · 토큰 갱신 · 로깅) · 취소 · 타임아웃 |
| dio + retrofit | API 가 많을 때 인터페이스에서 클라이언트 생성 |
| http | 요청이 적고 단순할 때 |

규칙: 클라이언트는 `core/network/` 하나 (기본 URL · 타임아웃 · 인증 인터셉터). 오류는 데이터 계층에서 앱 오류 타입(`core/error/`)으로 바꿔 올린다 — 화면이 `DioException` 을 모르게. 토큰 갱신 동시 요청은 한 번만 갱신(대기열). 요청 · 응답 로그에 `Authorization` · 쿠키 · 토큰을 남기지 않는다. `core/network/**` 는 위험 영역(`risk_areas`).

Firebase / Supabase: SDK 호출은 `data/` 의 데이터 소스 안에만. 화면 · 상태에서 SDK 를 직접 부르지 않는다. 보안 규칙(Firestore Rules · RLS)이 실제 권한이라는 것을 `project.md` 에 적는다.

### C2. 로컬 저장

| 선택지 | 메모 |
|---|---|
| **shared_preferences + flutter_secure_storage (추천)** | 설정 값 / 토큰 · 비밀 값 (토큰은 반드시 secure storage) |
| + drift | 관계형 데이터 · 오프라인 우선 · 검색 |
| 없음 | |

(Hive · Isar 는 유지 상태를 확인하고 사용자에게 알린 뒤에만 제안한다)

### C3. 다국어 · 테마

| 주제 | 선택지 |
|---|---|
| 다국어 | **한국어만 + gen-l10n 준비 (추천: 문자열을 ARB 로 모아 나중에 언어 추가)** · 처음부터 다국어 · 하드코딩 허용(프로토타입) |
| 디자인 | **Material 3 + 프로젝트 토큰 (`core/theme/`) (추천)** · 디자인 시스템(Figma 등) 있음 → 토큰을 옮겨 온다 · Cupertino 중심 |

### C4. 환경 분리

| 선택지 | 메모 |
|---|---|
| **dev · prod, `--dart-define-from-file=env/<환경>.json` (추천)** | 코드에서 `String.fromEnvironment`. `env/*.json` 커밋 금지, `env/*.example.json` 커밋 |
| + 네이티브 flavor | 앱 아이콘 · 번들 ID 를 환경별로 나눠 한 기기에 동시 설치할 때 (설정이 무겁다) |
| 하나만 | 프로토타입 |

### C5. 로깅

**`logger` 패키지를 `core/logging/` 에서 감싼 앱 로거 (추천)** · `dart:developer` `log` 래퍼 · (크래시 수집: Firebase Crashlytics · Sentry 는 백엔드 · 예산에 따라 따로 묻는다)

## D. 개발 방식

| 주제 | 선택지 | config · 규칙 |
|---|---|---|
| 브랜치 | **`main` 하나 — 기능 브랜치 → PR → Squash (추천: 1~3인)** · `dev` + `main` (dev 에서 개발, 출시 때 main 으로 승격) · `dev` + `staging` + `main` | `base_branch` · `protected_branches`, CI `push.branches` |
| Flutter 버전 | **fvm 으로 프로젝트에 고정 (추천)** · 시스템 Flutter | fvm 이면 `fvm use <버전>` → `.fvmrc` 커밋 (팩 명령이 자동으로 `fvm flutter` 를 쓴다), CI 도 같은 버전 |
| 테스트 정책 | **도메인 · 상태 · 데이터 변환은 TDD 필수, 화면은 핵심 위젯 테스트 (추천)** · 로직만 · 위젯까지 전부 | `architecture.md` · 팩 `testing.md` |
| 목 도구 | **mocktail (추천: 코드 생성 없음)** · mockito(+ build_runner) · 직접 만든 가짜 구현 | dev 의존성 |
| CI 범위 | **하네스 검사 + 포맷 · 분석 · 테스트 (추천)** · + Android · iOS 빌드 확인 · + 배포(스토어) 자동화는 나중에 따로 | `.github/workflows/ci.yml` |

---

## 만드는 파일 (선택 → 산출물)

| 산출물 | 내용 |
|---|---|
| `.harness/decisions/0001-initial-design.md` | 모든 주제의 선택 · 고려한 대안 · 이유 (`decisions/README.md` 형식) |
| `.harness/rules/project.md` | 개요 · 도메인 용어 · 핵심 결정 요약 · 브랜치 · 기능 목록 (60줄 이내, 항상 로드) |
| `.harness/rules/architecture.md` | `paths: ["lib/**"]` — 폴더 구조 · 계층 · 의존 방향 · 상태 관리 · 라우팅 · DI · 로깅 · 오류 처리 (위 "규칙에 쓸 것" 중 고른 것만) |
| `.harness/rules/data.md` | `paths:` 데이터 폴더 (예: `lib/features/**/data/**` · `lib/core/network/**`) — 네트워크 · DTO/엔티티 · 저장소 · 토큰 저장 (백엔드 · 저장소가 있을 때만) |
| `.harness/config.json` | `design_done: true` · `base_branch` · `protected_branches` · `layers` · `risk_areas`(예: `lib/core/network/**`, 인증 폴더) |
| 앱 골격 | `flutter create` → `analysis_options.yaml`(팩 템플릿) → 패키지 → 폴더 구조 · 앱 시작 코드 · 라우터 · 테마 · 로거 → 스모크 테스트 |
