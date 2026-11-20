---
description: 플랫폼 · 배포 설정 — Android · iOS 네이티브 설정 · 서명 · 권한 · 번들 ID · 환경 · CI/CD (위험 영역, L 경로)
paths:
  - "android/**"
  - "ios/**"
  - "macos/**"
  - "web/**"
  - ".github/**"
---

# 플랫폼 · 배포 (Flutter 팩)

이 파일의 대상은 모두 **위험 영역**이다 (`core.md` 작업 경로 L). 바꾸기 전에 계획을 공유하고 승인을 받는다.

## 식별자 · 서명

- 번들 ID(iOS) · applicationId(Android) · 앱 이름 · 버전 규칙은 `project.md` 결정을 따른다. 임의로 바꾸지 않는다.
- 서명 파일(`*.jks` · `*.keystore` · `key.properties` · `*.p12` · `*.mobileprovision`)을 만들거나 커밋하지 않는다. 서명은 CI Secret 이나 사용자 로컬에서만. (검사: `secret-file`, 훅: 차단)
- `google-services.json` · `GoogleService-Info.plist` · `firebase_options.dart` 는 공개 클라이언트 설정이라 커밋할 수 있다. 서버용 서비스 계정 키는 커밋하지 않는다.

## 권한 · 네이티브 설정

- 권한을 추가하면 iOS `Info.plist` 사용 목적 문구(`NS…UsageDescription`)와 Android `AndroidManifest.xml` 을 함께 맞추고, 사용자에게 보이는 문구는 사용자 확인을 받는다.
- `minSdkVersion` · iOS 최소 버전 · Gradle · CocoaPods 설정 변경은 이유와 영향(지원 기기)을 함께 보고한다.
- 환경(flavor)별 설정은 `project.md` 결정을 따른다 (`--dart-define-from-file` 이 기본).

## CI/CD (`.github/`)

- `.github/workflows/ci.yml` 의 하네스 검사(`Harness` job)를 끄거나 건너뛰게 바꾸지 않는다. 서브모듈 checkout(`submodules: true`)을 빼지 않는다.
- 배포 · 릴리스 · 스토어 업로드는 사용자가 하거나 사용자가 승인한 워크플로가 한다. 에이전트가 실행하지 않는다.
- 워크플로에서 Secret 을 출력하지 않는다 (`echo $SECRET` 금지).
