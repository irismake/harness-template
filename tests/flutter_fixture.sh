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
rm -f test/widget_test.dart
mkdir -p lib/features/home/presentation lib/features/home/domain
cat > lib/main.dart <<'EOF'
import 'package:fixture_app/features/home/presentation/home_screen.dart';
import 'package:flutter/material.dart';

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
cat > lib/features/home/presentation/home_screen.dart <<'EOF'
import 'package:flutter/material.dart';

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
c.update(design_done=True, layers=[{"files": "lib/features/**/domain/**", "forbid": ["package:flutter/material.dart", "/presentation/"],
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
printf "import 'package:flutter/material.dart';\nString greeting(String name) {  print(name);  return 'Hello, \$name'; }\n" > lib/features/home/domain/greeting.dart
expect_fail layer logging dart-format analyze-warning analyze-info
cp "$WORK/greeting.bak" lib/features/home/domain/greeting.dart

printf "void f(String accessToken) {\n  debugPrint('token=\$accessToken');\n}\n" > lib/features/home/domain/leak.dart
expect_fail sensitive-log logging
rm lib/features/home/domain/leak.dart

python3 .harness/core/scripts/harness.py verify >/dev/null || fail "원복 후 verify 실패"
echo "4. 위반 검출 · 원복 후 통과"

python3 .harness/core/scripts/harness.py test test/features/home/domain/greeting_test.dart >/dev/null || fail "harness test 실패"
flutter analyze >/dev/null || fail "flutter analyze 실패"
echo "5. harness test · flutter analyze 통과"
echo "✓ Flutter 팩 fixture 통과"
