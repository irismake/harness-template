#!/usr/bin/env bash
# Flutter 팩 fixture — 실제 Flutter 앱에 지금 하네스를 설치해 검사가 맞게 통과 · 실패하는지 본다.
# 사용: bash tests/flutter_fixture.sh   (flutter · dart 가 PATH 에 있어야 한다. 네트워크: pub get)
set -euo pipefail
TEMPLATE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
APP="$WORK/fixture_app"
fail() { echo "❌ $*" >&2; exit 1; }
expect_fail() {  # <검사 출력에 있어야 할 규칙 ID…>
  local out; out="$(python3 .harness/core/scripts/harness.py verify 2>&1)" && fail "위반이 있는데 verify 가 통과했다"
  for id in "$@"; do grep -q "\[$id\]" <<<"$out" || { echo "$out"; fail "[$id] 를 잡지 못했다"; }; done
  echo "  ✓ 잡음: $*"
}

mkdir -p "$APP" && cd "$APP"
git init -q -b main
git config user.name fixture && git config user.email fixture@example.com
mkdir -p .harness && cp -R "$TEMPLATE" .harness/core && rm -rf .harness/core/.git .harness/core/tests
python3 .harness/core/scripts/harness.py init flutter >/dev/null
echo "1. init"

flutter create --org com.example --project-name fixture_app --platforms android,ios . >/dev/null
grep -q 'harness:start' AGENTS.md || fail "flutter create 가 AGENTS.md 를 덮어썼다"
grep -q '.harness/out/' .gitignore || fail "flutter create 가 .gitignore 를 덮어썼다"
cp .harness/core/packs/flutter/templates/analysis_options.yaml analysis_options.yaml
# Material import 는 Flutter 버전마다 다르다 (3.50+: package:material_ui/material_ui.dart) — flutter create 가 만든 것을 따른다
MAT="$(grep -m1 -oE "package:[a-z_]+/material(_ui)?\.dart" lib/main.dart || echo package:flutter/material.dart)"
echo "  Material import: $MAT"
rm -f test/widget_test.dart
mkdir -p lib/features/home/presentation lib/features/home/domain
cat > lib/main.dart <<EOF
import 'package:fixture_app/features/home/presentation/home_screen.dart';
import '$MAT';

void main() {
  runApp(const App());
}

class App extends StatelessWidget {
  const App({super.key});

  @override
  Widget build(BuildContext context) {
    return const MaterialApp(home: HomeScreen());
  }
}
EOF
cat > lib/features/home/presentation/home_screen.dart <<EOF
import '$MAT';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(body: Center(child: Text('Fixture')));
  }
}
EOF
cat > lib/features/home/domain/greeting.dart <<'EOF'
String greeting(String name) => 'Hello, $name';
EOF
mkdir -p test/features/home/domain
cat > test/features/home/domain/greeting_test.dart <<'EOF'
import 'package:fixture_app/features/home/domain/greeting.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('이름을 넣으면 인사말을 만든다', () {
    expect(greeting('A'), 'Hello, A');
  });
}
EOF
cat > .harness/rules/architecture.md <<'EOF'
---
description: 폴더 구조 · 계층 (fixture)
paths:
  - "lib/**"
---

# 아키텍처
EOF
python3 - <<'EOF'
import json
p = ".harness/config.json"; c = json.load(open(p))
c.update(design_done=True, layers=[{"files": "lib/features/**/domain/**", "forbid": ["package:flutter/material.dart", "package:material_ui/", "/presentation/"],
                                    "message": "domain 은 UI · presentation 을 참조하지 않는다"}])
json.dump(c, open(p, "w"), indent=2)
EOF
flutter pub get >/dev/null
python3 .harness/core/scripts/harness.py sync >/dev/null
git add -A && git commit -q --no-verify -m "chore: fixture 골격"
echo "2. flutter create · 골격 · 규칙 · layers"

python3 .harness/core/scripts/harness.py verify >/dev/null || { python3 .harness/core/scripts/harness.py verify; fail "깨끗한 골격에서 verify 실패"; }
echo "3. verify 통과 (변경 없음)"

cp lib/features/home/domain/greeting.dart "$WORK/greeting.bak"
printf "import '$MAT';\nString greeting(String name) {  print(name);  return 'Hello, \$name'; }\n" > lib/features/home/domain/greeting.dart
expect_fail layer logging dart-format analyze-warning analyze-info
cp "$WORK/greeting.bak" lib/features/home/domain/greeting.dart

printf "void f(String accessToken) {\n  debugPrint('token=\$accessToken');\n}\n" > lib/features/home/domain/leak.dart
expect_fail sensitive-log logging
rm lib/features/home/domain/leak.dart

python3 .harness/core/scripts/harness.py verify >/dev/null || fail "원복 후 verify 실패"
echo "4. 위반 검출 · 원복 후 통과"

python3 .harness/core/scripts/harness.py test test/features/home/domain/greeting_test.dart >/dev/null || fail "harness test 실패"
out="$(flutter analyze 2>&1)" || { echo "$out"; fail "flutter analyze 실패 (팩 린트 설정이 이 Flutter 버전과 맞지 않을 수 있다)"; }
echo "5. harness test · flutter analyze 통과"
# ── TDD Guard (실제 flutter test 로) ──
python3 - <<'PY'
import json
p = ".harness/config.json"; c = json.load(open(p))
c["tdd"] = {"enabled": True, "paths": ["lib/features/**/domain/**"]}
json.dump(c, open(p, "w"), indent=2)
PY
git add -A && git commit -q --no-verify -m "chore: TDD Guard 켜기"
BASE="$(git rev-parse HEAD)"
SRC=lib/features/home/domain/counter.dart
TEST=test/features/home/domain/counter_test.dart
decision() { python3 -c 'import json,sys; print(json.dumps({"tool_name":"Write","tool_input":{"file_path":sys.argv[1]}}))' "$PWD/$1" \
  | python3 .harness/core/scripts/hooks/pre_tool.py | python3 -c 'import json,sys; d=sys.stdin.read(); print(json.loads(d)["hookSpecificOutput"]["permissionDecision"] if d.strip() else "allow")'; }
[ "$(decision $SRC)" = deny ] || fail "테스트 전 기능 코드 편집이 차단되지 않았다"
cat > $TEST <<'EOF2'
import 'package:fixture_app/features/home/domain/counter.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('1 을 올리면 2 가 된다', () {
    expect(increment(1), 2);
  });
}
EOF2
python3 .harness/core/scripts/harness.py test $TEST >/dev/null && fail "구현 전인데 테스트가 통과했다"
[ "$(decision $SRC)" = allow ] || fail "RED 확인 후에도 편집이 차단됐다"
echo "int increment(int value) => value;" > $SRC
python3 .harness/core/scripts/harness.py verify >/dev/null 2>&1 && fail "컴파일 실패 RED 만으로 verify 가 통과했다"
python3 .harness/core/scripts/harness.py test $TEST >/dev/null && fail "골격인데 테스트가 통과했다"
echo "int increment(int value) => value + 1;" > $SRC
python3 .harness/core/scripts/harness.py test $TEST >/dev/null || fail "구현 후 테스트가 실패했다"
python3 .harness/core/scripts/harness.py verify >/dev/null || { python3 .harness/core/scripts/harness.py verify; fail "RED → GREEN 후 verify 실패"; }
git add -A && git commit -q -m "feat: 카운터" || fail "RED → GREEN 후 커밋이 막혔다"
[ "$(decision $SRC)" = deny ] || fail "커밋 후에도 이전 RED 로 편집이 허용됐다"
python3 .harness/core/scripts/harness.py tdd ci --base "$BASE" >/dev/null || { python3 .harness/core/scripts/harness.py tdd ci --base "$BASE"; fail "CI RED 재현 실패"; }
echo "6. TDD Guard: 차단 → 컴파일 RED → 골격 → behavior RED → GREEN → verify · 커밋 → 재잠금 → CI RED 재현"
echo "✓ Flutter 팩 fixture 통과 ($(flutter --version | head -1))"
