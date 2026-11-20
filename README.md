# harness-template

**AI 코딩 에이전트(Claude Code · Codex)가 프로젝트 규칙을 지키며 일하게 만드는 하네스**를 여러 프로젝트에서 같이 쓰기 위한 템플릿이다.
새 Flutter 앱 폴더에 서브모듈로 넣고 `init` 한 번이면, 에이전트에게 "OO 앱을 만들고 싶어" 라고 말하는 순간부터 **설계 → 규칙 생성 → TDD 구현 → 자동 검증** 흐름으로 일한다.

- 지원 에이전트: **Claude Code** (규칙 자동 로드 · 훅 · 서브에이전트 · 스킬) · **Codex** (`AGENTS.md` 기반, 같은 원본)
- 지원 팩: **Flutter** (다른 언어는 `packs/` 에 팩을 추가하면 된다)
- 필요한 것: `git` · `python3` (3.9+) · Flutter (fvm 도 지원) · 선택: `gh`

---

## 목차

1. [하네스가 해 주는 것](#1-하네스가-해-주는-것)
2. [빠른 시작 — 새 Flutter 앱](#2-빠른-시작--새-flutter-앱)
3. [기존 Flutter 앱에 넣기 · 다른 사람이 클론할 때](#3-기존-flutter-앱에-넣기--다른-사람이-클론할-때)
4. [설계 단계 — `project-design`](#4-설계-단계--project-design)
5. [평소 작업 흐름](#5-평소-작업-흐름)
6. [구조 — 무엇이 어디에 있고 누가 고치나](#6-구조--무엇이-어디에-있고-누가-고치나)
7. [규칙이 에이전트에게 전달되는 방식](#7-규칙이-에이전트에게-전달되는-방식)
8. [검증 — 5겹의 검사](#8-검증--5겹의-검사)
9. [보호 장치 — 막는 것 · 묻는 것](#9-보호-장치--막는-것--묻는-것)
10. [`harness` 명령](#10-harness-명령)
11. [설정 — `.harness/config.json`](#11-설정--harnessconfigjson)
12. [프로젝트에 맞게 늘리기](#12-프로젝트에-맞게-늘리기)
13. [하네스 업데이트 (서브모듈 · 릴리스)](#13-하네스-업데이트-서브모듈--릴리스)
14. [피드백 루프 · 측정](#14-피드백-루프--측정)
15. [문제 해결](#15-문제-해결)
16. [한계 · 설계 원칙](#16-한계--설계-원칙)
17. [템플릿 고치기 · 검증 기록](#17-템플릿-고치기--검증-기록)

---

## 1. 하네스가 해 주는 것

에이전트는 똑똑하지만 **프로젝트의 약속을 모른 채** 시작한다. 하네스는 그 약속을 에이전트가 읽고 · 따르고 · 어기면 걸리게 만드는 장치다.

| 문제 | 하네스가 하는 일 |
|---|---|
| 에이전트마다 규칙 사본이 따로 놀고 서로 어긋난다 | 규칙 원본은 한 곳(`.harness/`). Claude 는 링크로, Codex 는 `AGENTS.md` 표로 **같은 파일**을 읽는다 |
| 규칙을 전부 컨텍스트에 넣으면 토큰이 많이 든다 | 항상 읽는 규칙은 2개(`core.md` · `project.md`)뿐. 나머지는 **작업 파일 경로에 맞을 때만** 로드 |
| 설계 없이 바로 코드를 짜기 시작한다 | `design_done: false` 면 먼저 `project-design` 스킬 — 선택지를 물어 **사용자가 고르고**, 결정 기록 · 규칙 · 골격을 만든다 |
| "테스트 통과했어요" 가 사실이 아니다 | TDD 절차(RED 확인 → GREEN)와 "실행하지 않은 검증은 보고하지 않는다" 규칙 |
| 규칙을 알아도 어긴다 (print · 토큰 로그 · 계층 위반 · 키 커밋) | 결정적 검사가 **편집 직후 · 응답 종료 전 · 커밋 전 · PR** 에서 잡는다 |
| 위험한 명령을 실행한다 (force push · 머지 · 배포 · Secret 수정) | 실행 전 훅이 **차단(deny)** 하거나 **사용자 확인(ask)** 을 띄운다 |
| 같은 실수를 반복한다 | `feedback` 스킬: 실수 → 검사 · 테스트 · 규칙으로 되돌리고 로그에 남긴다 |
| 하네스를 개선해도 프로젝트마다 복사해야 한다 | 공유 부분은 **git 서브모듈** — 정식 릴리스(태그)가 나오면 각 프로젝트에 업데이트 PR(Dependabot)이 열리고, 프로젝트 CI 를 통과하면 사람이 머지한다 |

---

## 2. 빠른 시작 — 새 Flutter 앱

```sh
# 1) 프로젝트 폴더 · git
mkdir -p ~/Documents/repo/my_app && cd ~/Documents/repo/my_app
git init -b main

# 2) 하네스를 서브모듈로 추가 — release 브랜치 = 최신 정식 릴리스
git submodule add -b release https://github.com/irismake/harness-template .harness/core

# 3) 설치 — 진입점 · 설정 · 링크 · git 훅 · CI · dependabot 생성
.harness/core/harness init flutter

# 4) 설치 결과 커밋
git add -A && git commit -m "chore: 하네스 설치"
```

`init` 이 만드는 것 (이미 있는 파일은 **덮어쓰지 않는다**)

```
my_app/
├─ AGENTS.md                      Codex 진입점 (+ 자동 생성되는 규칙 · 스킬 · 역할 표)
├─ CLAUDE.md                      Claude 진입점
├─ .claude/
│  ├─ settings.json               Claude 훅 3개 (실행 전 · 편집 직후 · 종료 전)
│  ├─ rules/{harness,flutter,project}/*.md   → 원본 심볼릭 링크
│  ├─ agents/{planner,reviewer}.md           → 원본 링크
│  └─ skills/{project-design,feature,bugfix,pr,feedback}/  → 원본 링크
├─ .github/
│  ├─ workflows/ci.yml            Harness job (하네스 검사) + Flutter job (포맷 · 분석 · 테스트)
│  └─ dependabot.yml              하네스 · Actions 업데이트 PR
├─ .gitignore                     Flutter 기본 항목 · env/*.json · .harness/out/ 추가
└─ .harness/
   ├─ core/                       ★ 서브모듈 (이 레포)
   ├─ config.json                 프로젝트 설정 (design_done: false)
   ├─ rules/project.md            프로젝트 개요 자리 (설계 때 채움)
   ├─ decisions/README.md         결정 기록 형식
   └─ feedback-log.md             실수 → 재발 방지 기록
```

그리고 `git config core.hooksPath .harness/core/githooks` (커밋 전 검사 · 커밋 메시지 검사)를 설정하고, `.gitmodules` 에 `branch = release` 가 없으면 넣는다 (`-b` 없이 추가했어도 업데이트는 정식 릴리스만 받게).

**5) 에이전트를 열고 말한다**

```
claude        # 또는 codex
> 동네 산책 기록 앱을 만들고 싶어. 산책 경로랑 사진을 남기고 친구랑 공유하는 거야.
```

에이전트는 `design_done: false` 를 보고 `project-design` 스킬로 설계부터 시작한다 → [4장](#4-설계-단계--project-design).

---

## 3. 기존 Flutter 앱에 넣기 · 다른 사람이 클론할 때

### 기존 Flutter 앱

```sh
cd 기존앱
git submodule add -b release https://github.com/irismake/harness-template .harness/core
.harness/core/harness init flutter
```

- `.gitignore` · `.github/workflows/ci.yml` 등이 이미 있으면 건드리지 않는다. 기존 CI 가 있으면 `.harness/core/packs/flutter/templates/ci.yml` 의 **Harness job** 만 옮겨 붙인다 (`submodules: true` checkout 필수).
- 에이전트에게 "하네스를 막 넣었어, 설계를 정리해 줘" 라고 하면 `project-design` 이 **지금 코드에서 선택을 추정**해 "이대로 기록할까, 바꿀까" 를 묻고, 골격 생성은 건너뛴다.
- 기존 코드의 위반은 세지 않는다 — 검사는 **추가된 줄**만 본다. 도입 후 고친 부분부터 규칙이 적용된다.

### 클론할 때 (중요)

```sh
git clone --recurse-submodules <프로젝트 URL>
# 이미 클론했다면
git submodule update --init
.harness/core/harness init      # git 훅 연결 (core.hooksPath 는 로컬 설정이라 클론마다 한 번)
```

서브모듈을 받지 않으면 `.harness/core` 가 비어 있다. 이때 Claude 훅과 git 훅은 **경고만 하고 통과**시키고(작업이 막히지 않게), CI 의 Harness job 이 다시 검사한다.

---

## 4. 설계 단계 — `project-design`

목표: 스킬이 끝나면 에이전트가 **규칙을 보고 바로 첫 기능을 TDD 로 만들 수 있는 상태**.

### 흐름

| 단계 | 내용 | 사용자가 하는 일 |
|---|---|---|
| 0. 상태 확인 | `config.json` · `pubspec.yaml` · `lib/` · 쓸 수 있는 Flutter 버전 | — |
| 1. 무엇을 만드나 | 앱 이름 · 조직 ID · 한 줄 설명 · 사용자 · 핵심 기능 · 참고 앱 · 목표 시점 | 자유롭게 설명 |
| 2. 제품 범위 | 플랫폼 · 백엔드 · 로그인 · 오프라인 | 선택 |
| 3. 아키텍처 | 상태 관리 · 폴더 구조 · 라우팅 · 모델/직렬화 | 선택 |
| 4. 데이터 · 인프라 | 네트워크 · 로컬 저장 · 다국어 · 디자인/테마 · 환경 분리 · 로깅 | 선택 (해당 없는 건 안 물음) |
| 5. 개발 방식 | 브랜치 전략 · Flutter 버전(fvm) · 테스트 정책 · 목 도구 · CI 범위 | 선택 |
| 6. 설계안 확인 | 결정 표 · 폴더 트리 · 패키지 목록 · 만들 파일 · 기능 구현 순서 | **승인** (여기 전엔 파일을 안 만든다) |
| 7. 만들기 | 결정 기록 → 골격 → 프로젝트 규칙 → 설정 → CI → sync · 테스트 · 분석 · verify | 패키지 설치 확인 창 승인 |
| 8. 보고 | 만든 것 · 실행 결과 · 커밋 제안 · 첫 기능 제안 | 첫 기능 고르기 |

- **질문 방식**: Claude 는 `AskUserQuestion` 도구로 선택지 화면을 띄운다 (한 번에 최대 4문항, 추천이 첫 번째에 "(추천)"). Codex 는 번호 목록으로 묻고 답을 기다린다.
- **추천은 앞 답에 따라 바뀐다**: 예) 백엔드가 Firebase 면 네트워크 질문 생략, 오프라인 우선이면 drift 추천, 1인 개발이면 `main` 단일 브랜치 추천.
- 모르겠다고 하면 추천을 쓰고 "사용자가 추천을 받아들임" 으로 기록한다.

### 고를 수 있는 것 (요약 — 전체는 [`packs/flutter/design/catalog.md`](packs/flutter/design/catalog.md))

| 주제 | 선택지 (굵게 = 기본 추천) |
|---|---|
| 상태 관리 | **Riverpod** · Bloc/Cubit · Provider |
| 폴더 구조 | **기능 우선 + 계층(domain · data · presentation)** · 계층 우선 · 단순 기능 폴더 |
| 라우팅 | **go_router** · auto_route · Navigator 직접 |
| 모델 | **freezed + json_serializable** · json_serializable 만 · 수동 |
| 네트워크 | **dio** · dio + retrofit · http · (Firebase · Supabase SDK) |
| 로컬 저장 | **shared_preferences + flutter_secure_storage** · + drift · 없음 |
| 다국어 · 디자인 | **한국어 + gen-l10n 준비** · **Material 3 + 프로젝트 토큰** · 디자인 시스템 옮기기 |
| 환경 | **dev · prod + `--dart-define-from-file`** · + 네이티브 flavor · 하나만 |
| 로깅 | **logger 래퍼** · `dart:developer` 래퍼 |
| 브랜치 | **`main` 하나 + Squash** · `dev`+`main` · `dev`+`staging`+`main` |
| Flutter 버전 | **fvm 고정(`.fvmrc`)** · 시스템 |
| 테스트 · 목 | **도메인 · 상태 TDD 필수 + 핵심 위젯** · **mocktail** |
| CI | **하네스 + 포맷 · 분석 · 테스트** · + Android/iOS 빌드 |

### 설계가 남기는 것

| 파일 | 내용 | 누가 읽나 |
|---|---|---|
| `.harness/decisions/0001-initial-design.md` | 주제별 선택 · 고려한 대안 · **이유** | 나중에 "왜 이렇게 했지?" 할 때 · planner · reviewer |
| `.harness/rules/project.md` | 개요 · 도메인 용어 · 핵심 결정 요약 · 브랜치 · 기능 목록 (60줄 이내) | **항상 로드** |
| `.harness/rules/architecture.md` | 폴더 구조 · 계층 · 의존 방향 · 상태 관리 · 라우팅 · 오류 · 로깅 — **고른 것만** | `lib/**` 작업 시 |
| `.harness/rules/data.md` | 네트워크 · DTO/엔티티 · 저장소 · 토큰 저장 (백엔드가 있으면) | 데이터 폴더 작업 시 |
| `.harness/config.json` | `design_done: true` · 브랜치 · `layers`(계층 위반 자동 검사) · `risk_areas` | 검사 · 훅 |
| 앱 골격 | `flutter create` · 린트 설정 · 패키지 · 폴더 · 앱 시작 · 라우터 · 테마 · 로거 · 스모크 테스트 | — |

결정을 나중에 바꾸려면 "상태 관리를 Bloc 으로 바꾸자" 처럼 말하면 된다. 스킬이 해당 주제만 다시 묻고 `0002-…md` 를 추가하며, 기존 기록은 "대체됨" 으로 남긴다.

---

## 5. 평소 작업 흐름

### 작업 경로 (S · M · L)

에이전트(메인 세션)가 요청을 받으면 경로를 판정한다. **메인 세션이 오케스트레이터 겸 구현자**다 — 구현 전담 에이전트를 따로 두지 않는다 (컨텍스트를 넘기는 비용 · 정보 손실이 더 크다).

| 경로 | 기준 | 흐름 |
|---|---|---|
| S | 문구 · 스타일 · 한 파일 단순 수정 | 바로 구현 |
| M | 한 계층 · 한 기능 안 | 계획 몇 줄 공유 → 구현 |
| L | 여러 계층, 또는 위험 영역 (`risk_areas` · 인증 · 네트워크 공통 · DI · 플랫폼 설정 · CI/CD · 서버 계약 · 동시성 · 결제) | **planner** 계획 → **사용자 승인** → 구현 → **reviewer** → 반영 → 재검토 1회까지 |

- 역할은 **planner · reviewer 둘뿐**, 역할마다 에이전트 하나 (같은 일을 여러 모델로 중복 실행하지 않는다 — 토큰).
- reviewer 에게는 **요구사항과 비교 기준 ref 만** 넘긴다. 구현 설명을 주지 않아야 독립적으로 본다.
- reviewer 지적은 "반영 / 반영 안 함(이유)" 으로 사용자에게 보고된다.

### 스킬 (반복 작업 절차)

| 스킬 | 언제 | 핵심 |
|---|---|---|
| `project-design` | 설계 전 · 구조 재결정 | 묻고 → 사용자가 고르고 → 기록 · 규칙 · 골격 |
| `feature` | 기능 추가 · 변경 · 리팩토링 | RED(기대한 이유로 실패 확인) → GREEN → REFACTOR → verify → 기능 목록 갱신 |
| `bugfix` | 버그 | 원인(코드 근거) → 재현 테스트 RED → 수정 GREEN → 재발 방지 제안 |
| `pr` | 커밋 · PR (**요청할 때만**) | 의도한 파일만 · `<type>: <요약>` · 본문 "테스트" 는 실제 실행 결과만 · 머지 안 함 |
| `feedback` | 실수 지적 · 반복 지적 · 규칙과 코드 불일치 | 원인 분류 → 가장 강한 재발 방지 수단 → 실제로 잡히는지 확인 → 로그 |

Claude 는 스킬 설명을 보고 알아서 고르고, `/feature` 처럼 직접 부를 수도 있다. Codex 는 `AGENTS.md` 표를 보고 해당 `SKILL.md` 를 읽는다.

### 예시 대화

```
나  > 산책 기록 목록 화면 만들어 줘
AI  > (M 경로) 계획: domain 에 Walk 엔티티 · WalkRepository, data 에 로컬 저장 구현,
      presentation 에 WalkListNotifier · WalkListScreen. 상태 전이부터 테스트합니다.
      → walk_list_notifier_test.dart 작성 → harness test … → 실패 확인(구현 없음) → 구현 → 통과
      → harness verify 통과 → project.md 기능 목록 "산책 목록: 완료"
나  > 커밋하고 PR 올려 줘
AI  > (pr 스킬) feat/walk-list 브랜치 · "feat: 산책 기록 목록 화면" · push 는 확인 창 → PR URL
```

### Claude 와 Codex 차이

| | Claude Code | Codex |
|---|---|---|
| 규칙 로드 | `.claude/rules/` 링크 · `paths` 로 자동 | `AGENTS.md` 지시대로 직접 읽음 |
| 스킬 · 역할 | 자동 등록 (`/스킬`, 서브에이전트) | `AGENTS.md` 표 → 파일을 읽고 따름. 독립 리뷰는 **새 세션** |
| 실행 전 차단 · 편집 직후 · 종료 전 검사 | 훅이 자동 | 없음 → `harness verify` 를 직접 실행 (AGENTS.md 지시) |
| git 훅 · CI | 같음 | 같음 — Codex 작업도 여기서 걸린다 |

---

## 6. 구조 — 무엇이 어디에 있고 누가 고치나

### 이 레포 (= 프로젝트의 `.harness/core/`)

```
harness-template/
├─ harness                     CLI 진입점 (→ scripts/harness.py)
├─ rules/core.md               공통 규칙 (항상 로드)
├─ agents/                     planner · reviewer
├─ skills/                     feature · bugfix · pr · feedback
├─ scripts/
│  ├─ harness.py               init · sync · verify · test · run · update · stats
│  ├─ lib.py                   경로 · 설정 병합(기본값 → 팩 → 프로젝트) · 팩 로딩 · 기본 보호 패턴
│  ├─ sync.py                  원본 → .claude 링크 · AGENTS.md 표
│  ├─ check_rules.py           하네스 구성 검사
│  ├─ check_code.py            변경분 코드 검사 (공통 + 팩 + 프로젝트)
│  ├─ events.py                검사 기록 (.harness/out/events.jsonl)
│  └─ hooks/                   Claude 훅: pre_tool · post_edit · stop
├─ githooks/                   pre-commit · commit-msg
├─ templates/                  init 이 프로젝트에 까는 파일
├─ packs/flutter/
│  ├─ pack.json                소스 · 테스트 폴더 · 명령 · Secret 파일 패턴 · 보호 패턴 · init 파일 · gitignore
│  ├─ rules/                   flutter.md (*.dart) · testing.md (test/**) · platform.md (android/** · ios/** · .github/**)
│  ├─ checks.py                print · 로그 속 인증 정보 · dart format · dart analyze
│  ├─ skills/project-design/   설계 스킬
│  ├─ design/catalog.md        설계 선택지 · 추천 · 고른 뒤 만들 규칙 · layers
│  └─ templates/               ci.yml · analysis_options.yaml
└─ tests/test_harness.py       템플릿 회귀 테스트
```

### 소유 구분

| 위치 | 소유 | 고치는 곳 |
|---|---|---|
| `.harness/core/**` | **공유** (모든 프로젝트) | 이 템플릿 레포에서만. 프로젝트 안에서 고치면 훅이 막고 `check-rules` 가 실패한다 |
| `.harness/config.json` · `rules/` · `decisions/` · `feedback-log.md` · `checks.py` · `skills/` · `agents/` | **프로젝트** | 프로젝트에서 (설정 · 검사는 확인 창) |
| `.claude/rules` · `agents` · `skills` 링크, `AGENTS.md` 의 harness 블록 | **생성물** | 직접 고치지 않는다 → `harness sync` |
| `AGENTS.md` · `CLAUDE.md` 나머지 · `.claude/settings.json` · `.github/` | 프로젝트 (init 이 처음 한 번 생성) | 프로젝트에서 |

---

## 7. 규칙이 에이전트에게 전달되는 방식

```
            원본 (여기만 고친다)                                 Claude Code                         Codex
 .harness/core/rules/core.md          ── 링크 ──▶ .claude/rules/harness/core.md      (항상)   ◀── AGENTS.md "항상 읽는 규칙"
 .harness/rules/project.md            ── 링크 ──▶ .claude/rules/project/project.md   (항상)   ◀──        〃
 .harness/core/packs/flutter/rules/*  ── 링크 ──▶ .claude/rules/flutter/*.md         (paths)  ◀── AGENTS.md "작업 대상별 규칙" 표
 .harness/rules/architecture.md …     ── 링크 ──▶ .claude/rules/project/*.md         (paths)  ◀──        〃
 skills/*/SKILL.md · agents/*.md      ── 링크 ──▶ .claude/skills/* · .claude/agents/*         ◀── AGENTS.md 스킬 · 역할 표
```

- **frontmatter** 가 전달 방식을 정한다. `description` 은 표에 쓰이고, `paths` 는 Claude 가 언제 로드할지 정한다.

  ```markdown
  ---
  description: 네트워크 · DTO/엔티티 · 저장소
  paths:
    - "lib/features/**/data/**"
    - "lib/core/network/**"
  ---
  ```

- `paths` 가 없는 규칙은 항상 로드된다 → `core.md` · `project.md` 만 허용 (`always_loaded_rules`). 다른 규칙에 `paths` 가 없으면 `check-rules` 가 실패한다. 상시 토큰을 작게 유지하기 위해서다.
- 같은 이름의 스킬 · 역할은 **프로젝트 > 팩 > 코어** 순으로 이긴다 (예: 프로젝트 전용 `feature` 스킬로 덮어쓰기).
- 규칙을 추가 · 삭제했으면 `harness sync`. 잊으면 편집 직후 · 종료 전 훅 · pre-commit · CI 의 `check-rules` 가 알려 준다.

---

## 8. 검증 — 5겹의 검사

같은 검사를 여러 지점에서 돌린다. 앞에서 잡을수록 싸다.

| # | 지점 | 언제 | 무엇을 | 위반 시 |
|---|---|---|---|---|
| 1 | Claude **실행 전 훅** (`pre_tool.py`) | 명령 · 파일 편집 직전 | 위험 명령 · 보호 파일 ([9장](#9-보호-장치--막는-것--묻는-것)) | 차단 또는 확인 창 |
| 2 | Claude **편집 직후 훅** (`post_edit.py`) | `.dart` 파일 하나 고친 직후 | 그 파일의 코드 검사 + 포맷 + 분석 | Claude 에게 결과를 돌려줘 **그 자리에서 고치게** 한다 |
| 3 | Claude **종료 전 훅** (`stop.py`) = `harness verify` | 응답을 끝내기 전 | 하네스 구성 + 작업 브랜치 전체 변경분 | 한 번 막고 고치게 한다. 두 번째는 보고하게 둔다 (무한 반복 방지) |
| 4 | **git 훅** (`pre-commit` · `commit-msg`) | 커밋할 때 (Claude · Codex · 사람 공통) | stage 된 변경 + 포맷 · 분석, 하네스 파일이 바뀌었으면 구성 검사 / 메시지 형식 | 커밋 거부 |
| 5 | **CI** (`Harness` · `Flutter` job) | PR · main push · merge queue | 구성 검사 + PR 변경분 코드 검사 (줄 단위 PR 주석) / 포맷 · `flutter analyze` · `flutter test` | PR 실패 — Required check 로 지정하면 머지 불가 |

- 로컬 검사(2~4)는 **수 초**다. 빌드 · 전체 테스트는 넣지 않는다 — CI 가 한다.
- 모든 검사는 **추가된 줄 · 새 파일**만 본다. 기존 코드의 위반은 세지 않는다.
- 판단이 필요한 것(요구사항 충족 · 설계 적합성)은 검사하지 않는다 → reviewer.

### 검사 목록

| ID | 무엇 | 출처 |
|---|---|---|
| `harness-sync` | 링크 누락 · 끊김 · 사본 · AGENTS.md 표 불일치 · frontmatter · 다른 도구용 사본(`.cursorrules` 등) · 서브모듈 안 수정 | `check_rules.py` |
| `secret-file` | 키 · 인증서 · `.env` · `key.properties` · `env/*.json` · 서비스 계정 키 파일 커밋 (`git add -f` 포함) | 공통 + 팩 |
| `secret-value` | 개인 키 · GitHub · AWS · Slack · Google · AI · Stripe 키 형식의 값 (Firebase 클라이언트 설정 파일은 제외) | 공통 |
| `layer` | `config.json` `layers` 의 경로별 금지 import (예: domain 이 `material.dart` · `/data/` 참조) | 공통 (설정은 설계가 만든다) |
| `logging` | `lib/` 에서 `print` · `debugPrint` | Flutter 팩 |
| `sensitive-log` | 로그 호출 문자열 보간에 token · password · secret · authorization · cookie 등 (`${token != null}` 처럼 상태만은 허용) | Flutter 팩 |
| `dart-format` · `analyze-*` | `dart format` · `dart analyze` (프로젝트 `analysis_options.yaml`) — dart 가 없거나 `pub get` 전이면 건너뜀 | Flutter 팩 (`--lint`) |
| (프로젝트 ID) | `.harness/checks.py` 에 프로젝트가 추가한 검사 | 프로젝트 |

---

## 9. 보호 장치 — 막는 것 · 묻는 것

Claude 의 실행 전 훅이 적용한다. 패턴 = 코어 기본값([`scripts/lib.py`](scripts/lib.py) `DEFAULTS`) + 팩([`pack.json`](packs/flutter/pack.json)) + 프로젝트(`config.json` `protected`).
Codex 에는 훅이 없으므로 `core.md` 의 "사용자 승인 없이 하지 않는다" 를 스스로 지키고, git 훅 · CI 가 뒤에서 다시 본다.

**차단 (deny)**

- 명령: `git reset --hard` · `git clean -f` · 강제 push · 원격 브랜치 삭제 · **보호 브랜치에 직접 push** (`protected_branches`) · `gh pr merge` · `gh workflow run` · `gh release create/…` · `gh secret` · `fastlane` · `firebase deploy` · 서명 키 생성(`keytool -genkey`)
- 파일: **`.harness/core/**`** (공유 하네스) · `.env*` · 인증서 · 키(`*.p8` · `*.p12` · `*.jks` · `*.keystore` …) · `key.properties` · `env/*.json` (예시 `env/*.example.json` 은 허용) · 서비스 계정 키 · `.git/`

**확인 창 (ask)**

- 명령: `git push` · `gh pr create/edit/close/ready` · `gh api` 쓰기 · `git submodule update --remote` (하네스 업데이트) · `flutter|dart pub add/remove/upgrade` · `flutterfire configure` · 릴리스 빌드
- 파일: `.github/**` · `.claude/settings*.json` · `.harness/config.json` · `.harness/checks.py` · `fastlane/**` · `pubspec.yaml` · `analysis_options.yaml` · `android/` · `ios/` · `macos/` · 생성 파일(`*.g.dart` · `*.freezed.dart` …)

"하네스 우회 방지" 항목(설정 · 검사 · 린트 설정)이 확인 창인 이유: 에이전트가 검사에 걸렸을 때 **검사 쪽을 고쳐서** 통과시키는 것을 막기 위해서다.

---

## 10. `harness` 명령

프로젝트 루트에서 `.harness/core/harness <명령>`. (자주 쓰면 `alias harness=.harness/core/harness`)

| 명령 | 하는 일 |
|---|---|
| `init <팩>` | 설치. 다시 실행해도 안전 (있는 파일은 그대로, 링크 · 표 · git 훅만 맞춘다) |
| `sync` | `.claude` 링크와 `AGENTS.md` 표를 원본에 맞춰 다시 만든다 |
| `verify [--base <ref>]` | 작업 마치기 전 검사 = `check-rules` + `check-code --lint`. 기본 기준은 `origin/<base_branch>` |
| `check-rules` | 하네스 구성 검사 |
| `check-code [--base R \| --staged \| --file F] [--lint]` | 변경분 코드 검사 |
| `test <파일·폴더…>` | 관련 테스트만 (`commands.test`, `.fvmrc` 가 있으면 `fvm flutter test`). 전체는 `--all` |
| `run <이름> [...]` | `commands` 의 명령 — `codegen`(build_runner) · `format` · `analyze` · 프로젝트가 추가한 것 |
| `update` | 최신 **정식 릴리스**(`release` 브랜치)를 받고 sync · 구성 검사, 버전 변화 · 커밋 목록 · CHANGELOG 표시. 커밋은 직접 |
| `stats [--since 2026-11-01]` | 로컬 검사 기록 집계 — 실행 위치별 통과/위반, 규칙별 위반, 차단 · 확인 이유 |

---

## 11. 설정 — `.harness/config.json`

값은 **코어 기본값 → 팩(`pack.json`) → 프로젝트(`config.json`)** 순으로 합쳐진다. 리스트는 이어 붙고, 값은 덮어쓴다.

| 키 | 기본값 | 뜻 |
|---|---|---|
| `pack` | — | 팩 이름 (`flutter`) |
| `design_done` | `false` | `false` 면 에이전트가 설계부터 한다 |
| `base_branch` | `main` | 작업 브랜치를 따는 곳 · `verify` 비교 기준 |
| `protected_branches` | `["main"]` | 직접 push 차단 |
| `branch_prefixes` | feat · fix · refactor · chore · docs · test · style · ci · hotfix | 브랜치 이름 규칙 |
| `commit_types` | feat · fix · refactor · chore · docs · test · style · ci · build · perf · revert | 커밋 메시지 `<type>:` (commit-msg 훅) |
| `always_loaded_rules` | `core.md` · `project.md` | `paths` 없이 허용되는 규칙 |
| `source_dirs` · `test_dirs` | 팩: `lib/` · `test/` `integration_test/` | 편집 직후 검사 대상 |
| `risk_areas` | 팩: `android/**` · `ios/**` · … · `pubspec.yaml` | L 경로 판정 기준 (설계가 네트워크 · 인증 폴더를 더한다) |
| `commands` | 팩: test · test_all · format · analyze · codegen | `harness test` · `harness run`. `{flutter}` · `{dart}` 는 fvm 여부에 따라 바뀐다 |
| `layers` | `[]` | `{"files": glob, "forbid": [문자열…], "message", "rule"}` — 경로별 금지 import |
| `secret_files` · `secret_value_allow` | 코어 + 팩 | 커밋 금지 파일 패턴 · 키 값 검사 제외 파일 |
| `protected` | 코어 + 팩 | `bash_deny` · `bash_ask` · `file_deny` · `file_ask` (`[정규식, 이유]`) · `file_allow` (정규식) |

예: `dev` + `main` 전략, 결제 폴더를 위험 영역으로

```json
{
  "pack": "flutter",
  "design_done": true,
  "base_branch": "dev",
  "protected_branches": ["dev", "main"],
  "risk_areas": ["lib/core/network/**", "lib/features/payment/**"],
  "layers": [
    {"files": "lib/features/**/domain/**", "forbid": ["package:flutter/material.dart", "/data/", "/presentation/"],
     "message": "domain 은 UI · data · presentation 을 참조하지 않는다", "rule": ".harness/rules/architecture.md"}
  ],
  "protected": {
    "file_ask": [["(^|/)lib/core/network/", "네트워크 공통 변경은 확인 필요"]]
  }
}
```

---

## 12. 프로젝트에 맞게 늘리기

| 하고 싶은 것 | 방법 |
|---|---|
| 규칙 추가 | `.harness/rules/<이름>.md` (frontmatter `description` · `paths`) → `harness sync` |
| 프로젝트 전용 스킬 · 역할 | `.harness/skills/<이름>/SKILL.md` · `.harness/agents/<이름>.md` → `harness sync` (같은 이름이면 코어 것을 덮어쓴다) |
| 결정적 검사 추가 | `.harness/checks.py` — 아래 형식. 팩 검사 [`packs/flutter/checks.py`](packs/flutter/checks.py) 가 예시 |
| 계층 · import 규칙 | `config.json` `layers` |
| 차단 · 확인 패턴 | `config.json` `protected` |
| 명령 추가 | `config.json` `commands` (예: `"e2e": "{flutter} test integration_test"` → `harness run e2e`) |
| Claude · Codex 전용 지침 | `CLAUDE.md` · `AGENTS.md` 의 "프로젝트 전용 지침" 칸 (공통은 `.harness/rules/`) |

`.harness/checks.py` 형식

```python
def check(ctx):
    # ctx.added: {경로: [(줄번호, 추가된 줄)]}  ctx.new: {새 파일}  ctx.cfg · ctx.root · ctx.is_comment(text)
    for path, lines in ctx.added.items():
        if not path.startswith("lib/features/") or not path.endswith(".dart"):
            continue
        for no, text in lines:
            if "Colors." in text and not ctx.is_comment(text):
                ctx.report("raw-color", path, no, "테마 색(Theme.of(context).colorScheme)을 쓴다", ".harness/rules/ui.md")

def lint(ctx, paths):        # 선택 — --lint 일 때
    ...
```

**모든 프로젝트에 해당하는 개선**(코어 · 팩 규칙이 틀렸다, 검사에 구멍이 있다)은 프로젝트에서 우회하지 말고 이 레포에 이슈 · PR 로 올린다.

---

## 13. 하네스 업데이트 (서브모듈 · 릴리스)

### 버전 · 릴리스

| | 뜻 |
|---|---|
| `VERSION` 파일 | 현재 버전 (예: `0.1.0`). 태그와 항상 같다 |
| Git 태그 `vX.Y.Z` | 정식 릴리스 후보. push 하면 릴리스 워크플로가 돈다 |
| `release` 브랜치 | **정식 릴리스만** 가리킨다. 릴리스 워크플로가 Template CI 를 다시 통과한 태그 커밋으로만 옮긴다 (fast-forward) |
| `main` 의 일반 커밋 | 개발 중. 프로젝트 업데이트 대상이 **아니다** |

프로젝트 서브모듈은 `.gitmodules` 의 `branch = release` 를 따라간다 (`submodule add -b release`, 없으면 `harness init` 이 넣는다). 그래서 Dependabot 도 `harness update` 도 정식 릴리스만 본다.

### 전체 흐름

```
하네스 변경 (템플릿 레포 PR)
  ↓ Template CI (test.yml)            회귀 테스트 · Flutter 앱 fixture · 이전 릴리스 → 지금 업그레이드
main 머지
  ↓ VERSION · CHANGELOG 올리고 태그 vX.Y.Z push
릴리스 워크플로 (release.yml)          태그 = VERSION · CHANGELOG 항목 · main 에 있는 커밋 · Template CI 재실행
  ↓ 모두 통과하면 release 브랜치 → 태그 커밋     (하나라도 실패하면 release 는 그대로 = 배포 안 됨)
각 프로젝트 Dependabot (매주)           release 브랜치에서 새 태그 커밋 발견 → "bump .harness/core from vA to vB" PR
  ↓ 프로젝트 CI (ci.yml) 전체          새 하네스로 checkout(submodules: true) → harness verify · 포맷 · 분석 · 테스트 (· 빌드)
PASS → 사람이 머지 / FAIL → 머지하지 않음 (기존 버전 유지) · 프로젝트 수정 또는 하네스 수정
```

두 CI 는 묻는 것이 다르다.

| | 묻는 것 | 실패하면 |
|---|---|---|
| **Template CI** | "하네스 자체가 정상인가?" | 릴리스하지 않는다 |
| **Project Update PR CI** | "이 하네스 버전을 **이 프로젝트에** 적용해도 정상인가?" | 그 프로젝트만 업데이트를 보류한다 |

Template CI 통과가 모든 프로젝트의 통과를 뜻하지 않는다. 예를 들어 v1.0.3 에서 A · C 는 통과하고 B 는 새 규칙과 기존 코드가 부딪혀 실패할 수 있다. 이게 정상이다 — B 는 업데이트 PR 을 머지하지 않고 기존 버전을 쓴다.

### 자동 적용 없음

- Dependabot 설정 · 워크플로 어디에도 자동 머지가 없다. 업데이트는 항상 **PR → 프로젝트 CI → 사람이 머지**.
- 서브모듈은 커밋을 고정한다. 템플릿 `main` 이나 `release` 가 바뀌어도 프로젝트가 쓰는 하네스는 업데이트 PR 을 머지하기 전까지 그대로다.
- 브랜치 보호에서 `Harness` · `Flutter` job 을 Required check 로 지정하면 실패한 업데이트 PR 은 머지 버튼 자체가 막힌다 (GitHub 설정 — 사용자가 한다).

### 업데이트 PR 을 받았을 때

- 통과: 변경 내역(PR 본문 · `CHANGELOG.md`)을 보고 머지 → 로컬에서 `git pull && git submodule update && .harness/core/harness sync`
- `Harness` job 이 **"링크가 없습니다 / AGENTS.md 표가 원본과 다릅니다"** 로 실패: 새 버전에 규칙 · 스킬이 추가됐다. PR 브랜치를 받아 `git submodule update && .harness/core/harness sync` 후 커밋 · push → CI 재실행
- 새 규칙 · 검사에 기존 코드가 걸려 실패: 머지하지 않는다. 프로젝트 코드를 고치거나, 하네스 쪽이 틀렸으면 템플릿 레포에 이슈

### 수동으로 받기

```sh
.harness/core/harness update    # release 브랜치의 최신 정식 릴리스 받기 + 버전 · 변경 내역 + sync + 구성 검사
git add .harness/core .claude AGENTS.md && git commit -m "chore: 하네스 업데이트"   # PR 로 올려 CI 를 거친다
```

### 주의

- 프로젝트 안의 `.harness/core` 에서 고치지 않는다 (훅이 막고 `check-rules` 가 실패). 템플릿 레포에서 고쳐 릴리스한다.
- init 은 있는 파일을 덮어쓰지 않으므로, 템플릿 파일(`ci.yml` 등)이 바뀐 릴리스는 CHANGELOG 의 "할 일" 을 보고 직접 옮긴다.
- 특정 릴리스에 고정: `git -C .harness/core checkout v0.1.0` 후 포인터 커밋. Dependabot PR 은 닫거나 `ignore` 설정.
- 릴리스 방법(관리자)은 [CONTRIBUTING.md](CONTRIBUTING.md#릴리스).

---

## 14. 피드백 루프 · 측정

### 실수 → 재발 방지 (`feedback` 스킬)

사용자가 실수를 지적하거나 같은 유형이 반복되면, 기록만 하지 않고 **다음에 자동으로 걸리게** 만든다.

| 우선 | 수단 | 예 |
|---|---|---|
| 1 | 결정적 검사 | `layers` 추가 · `.harness/checks.py` · `protected` 패턴 · 린트 규칙 |
| 2 | 회귀 테스트 | 경계 조건 버그를 테스트로 고정 |
| 3 | 규칙 문구 · `paths` 보강 | 판단이 필요한 것 |
| 4 | 로그만 | 위가 모두 불가할 때 (이유 필수) |
| T | 템플릿에 제안 | 코어 · 팩이 틀렸거나 모든 프로젝트에 해당 |

일부러 같은 실수를 만들어 **실제로 잡히는지** 확인한 뒤 `.harness/feedback-log.md` 에 한 줄 남긴다. 규칙이 실제 코드와 다르면 코드가 아니라 **규칙을 코드에 맞춘다**.

### 측정 (`harness stats`)

Claude 훅 · git 훅 · verify 가 결과를 `.harness/out/events.jsonl`(gitignore)에 남긴다. 시각 · 실행 위치 · 결과 · 규칙 ID · 파일 경로 · 차단 이유만 — **명령 내용 · 코드 · Secret 은 남기지 않는다.** CI 와 수동 실행은 기록하지 않는다.

```
$ .harness/core/harness stats
| 실행 위치 | 결과 | 횟수 |
| claude-post-edit | fail | 3 |     ← 편집 직후에 잡아 그 자리에서 고친 횟수
| git-pre-commit   | pass | 12 |
| claude-pre-tool  | deny | 1 |
| 규칙 | 위반 |
| logging | 2 |
```

보는 법: 같은 규칙 위반이 계속 나오면 규칙이 실제와 맞지 않거나 더 강한 수단이 필요하다는 신호. 정상 작업이 `deny` 로 자주 막히면 패턴이 너무 넓다는 신호.

---

## 15. 문제 해결

| 증상 | 원인 · 해결 |
|---|---|
| `.harness/core` 가 비어 있다 · 훅이 "비어 있습니다" 경고 | 서브모듈을 안 받았다 → `git submodule update --init` |
| 커밋 훅이 안 돈다 | 클론마다 `core.hooksPath` 설정 필요 → `.harness/core/harness init` (안전하게 다시 실행 가능) |
| `check-rules`: "링크가 없습니다" · "AGENTS.md 표가 원본과 다릅니다" | 규칙 · 스킬을 추가 · 삭제했거나 하네스를 업데이트했다 → `harness sync` |
| `check-rules`: "paths 에 맞는 파일이 하나도 없습니다" | 폴더 이름이 바뀌었다 → 규칙 `paths` 를 실제 경로로 고친다 |
| `check-rules`: "공유 하네스가 프로젝트 안에서 수정됐습니다" | `.harness/core` 안을 고쳤다 → `git -C .harness/core checkout .` 로 되돌리고 템플릿 레포에서 고친다 |
| Claude 가 규칙을 안 따르는 것 같다 | Claude Code 에서 `/memory` 로 로드된 파일 확인. 폴더를 처음 열 때 나오는 **신뢰 확인**을 승인해야 프로젝트 지침이 로드된다. 작업 파일이 규칙 `paths` 에 맞는지 확인 |
| 포맷 · 분석이 "건너뜀" | dart 가 PATH 에 없거나(`fvm` 이면 `.fvmrc` 확인) `flutter pub get` 전 — CI 가 다시 검사한다 |
| 실행 전 훅이 문자열 속 명령도 막는다 (예: 테스트 데이터에 든 `push --force`) | 셸 구문을 해석하지 않고 명령 전체에서 패턴을 찾기 때문 (안전 쪽 오탐). 파일 편집 도구를 쓰거나 스크립트 파일로 분리 |
| 정상 명령이 계속 막힌다 | `harness stats` 의 차단 이유 확인 → 프로젝트는 `config.json` 으로는 패턴을 **더할** 수만 있다. 코어 · 팩 패턴이 넓으면 이 레포에 이슈 |
| Codex 가 검사를 안 한다 | Codex 에는 훅이 없다. `AGENTS.md` 가 `harness verify` 를 지시하고, 커밋 · PR 에서 git 훅 · CI 가 잡는다 |

---

## 16. 한계 · 설계 원칙

**한계**

- Codex 에는 Claude 같은 훅이 없어 실행 전 차단 · 편집 직후 검사가 없다. git 훅과 CI 가 그 몫을 한다.
- 실행 전 훅은 정규식이다. 우회하려는 의도까지 막지는 못한다 — 사람의 승인 · 브랜치 보호 · CI 가 최종 방어선이다.
- 결정적 검사는 패턴으로 판정할 수 있는 것만 본다. 설계 품질 · 요구사항 충족은 reviewer 와 사람이 본다.
- 프로젝트는 코어 · 팩의 보호 패턴을 **뺄 수 없다** (더하기만 가능). 의도된 제약이다.
- GitHub 브랜치 보호 · Required check 설정은 하네스가 하지 않는다 (사용자 권한 · 외부 설정). 설계 스킬이 안내만 한다.

**원칙**

1. **원본은 하나** — 사본을 만들지 않고 링크 · 생성으로 전달한다.
2. **상시 컨텍스트는 작게** — 항상 로드는 2개, 나머지는 경로로.
3. **결정은 사람이** — 에이전트는 선택지와 추천을 내고, 패키지 · 커밋 · push · 머지 · 배포는 승인 후에만.
4. **문서보다 검사** — 패턴으로 판정할 수 있는 규칙은 검사로 만든다. 실수는 더 강한 수단으로 되돌린다.
5. **빠른 검사는 로컬, 느린 검사는 CI** — 로컬은 수 초, 빌드 · 전체 테스트는 CI.
6. **공유는 서브모듈, 프로젝트 것은 프로젝트에** — 업데이트는 확인하고 받는다.

---

## 17. 템플릿 고치기 · 검증 기록

고치는 방법 · 기준은 [CONTRIBUTING.md](CONTRIBUTING.md), 변경 내역은 [CHANGELOG.md](CHANGELOG.md).

```sh
python3 -m unittest discover -s tests -v   # 임시 프로젝트에 설치해 끝까지 — Flutter 불필요, 약 20초
bash tests/flutter_fixture.sh               # 실제 Flutter 앱 fixture — flutter 필요, 1~2분
```

### 0.1.0 검증 기록 (2026-11-20)

| 항목 | 방법 | 결과 |
|---|---|---|
| 회귀 테스트 22개 | init · 재실행 안전 · 구성 검사 · sync 복구 · 사본 거부 · 프로젝트 스킬 우선 · Secret · 로그 · 계층 · 기존 위반 제외 · 프로젝트 검사 · git 훅 · 편집 직후 · 종료 전 훅 · 실행 전 훅 명령 13종 · 파일 12종 · 보호 브랜치 설정 · 서브모듈 수정 감지 · release 브랜치만 추적 · 새 릴리스 받기 · `-b` 없이 추가 시 보정 · 이전 릴리스 → 지금 업그레이드 | ✅ (Python 3.9) |
| 실제 Flutter 앱 | 서브모듈 추가 → init → fvm 3.35.0 · `flutter create` → 린트 템플릿 · Riverpod · go_router · logger · mocktail → 골격 · 규칙 · layers → `harness test` · `run analyze` · `verify` | ✅ 테스트 통과 · 분석 0건 · verify 통과 · `flutter create` 가 `.gitignore` · `AGENTS.md` 를 덮어쓰지 않음 |
| 위반 검출 (실제 앱) | domain 에 `material.dart` import · `print` · 포맷 깨짐 | ✅ `layer` · `logging` · `dart-format` · `analyze-warning` · `analyze-info` |
| Claude 규칙 · 스킬 · 역할 로드 | 헤드리스 세션 기록 (Claude Code 2.1.322 · 2.1.328) | ✅ 시작 시 `CLAUDE.md` · `core.md` · `project.md`, `lib/main.dart` 를 읽으면 `architecture.md` · `flutter.md` 추가 (`testing.md` 는 안 읽힘 — 의도대로). 스킬 5 · 역할 2 등록. (2.1.328 은 임시 폴더에서 링크 없는 `CLAUDE.md` 도 읽지 않아 — 폴더 신뢰 · 경로 요인 — 규칙 로드는 2.1.322 로 확인, 스킬 · 역할 등록은 두 버전 모두 확인) |
| Flutter 팩 fixture (`tests/flutter_fixture.sh`) | init → `flutter create` 가 진입점을 덮어쓰지 않음 → verify 통과 → 위반 7종 검출 → 원복 후 통과 → `harness test` · `flutter analyze` | ✅ |
| Codex | 이 머신에 Codex CLI 가 없어 실행 확인 못 함 | ⚠️ `AGENTS.md` 생성 · 링크만 정적 확인 |
