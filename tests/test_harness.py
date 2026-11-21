"""
하네스 템플릿 회귀 테스트 — 임시 프로젝트에 지금 작업 트리를 .harness/core 로 설치해 끝까지 돌려 본다.

실행: python3 -m unittest discover -s tests -v   (Flutter 없이 돈다 — 포맷 · 분석은 dart 가 없으면 건너뜀)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1]
ENV = {k: v for k, v in os.environ.items()
       if k not in {"HARNESS_SOURCE", "HARNESS_PROJECT_ROOT", "GITHUB_ACTIONS", "CLAUDECODE", "HARNESS_AGENT"} and not k.startswith(("CODEX_", "CLAUDE_CODE"))}
ENV.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")


class Project:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "my_app"
        self.root.mkdir()
        self.run("git", "init", "-q", "-b", "main")
        shutil.copytree(TEMPLATE, self.root / ".harness/core",
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "tests"))

    def run(self, *args, input=None, check=True):
        r = subprocess.run(args, cwd=self.root, capture_output=True, text=True, input=input, env=ENV)
        if check and r.returncode != 0:
            raise AssertionError(f"{args} 실패\n{r.stdout}\n{r.stderr}")
        return r

    def harness(self, *args, check=True):
        return self.run(sys.executable, ".harness/core/scripts/harness.py", *args, check=check)

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def hook(self, name, payload):
        return self.run(sys.executable, f".harness/core/scripts/hooks/{name}.py", input=json.dumps(payload), check=False)

    def decision(self, payload):
        out = self.hook("pre_tool", payload).stdout.strip()
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else "allow"

    def commit(self, message="chore: test", verify=True):
        self.run("git", "add", "-A")
        return self.run("git", "commit", "-q", "-m", message, *([] if verify else ["--no-verify"]), check=False)


class InitTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.p.harness("init", "flutter")

    def tearDown(self):
        self.p.tmp.cleanup()

    def test_init_creates_entry_points_and_links(self):
        r = self.p.root
        for f in ["AGENTS.md", "CLAUDE.md", ".claude/settings.json", ".harness/config.json", ".harness/rules/project.md",
                  ".harness/feedback-log.md", ".harness/decisions/README.md", ".github/workflows/ci.yml", ".github/dependabot.yml"]:
            self.assertTrue((r / f).exists(), f)
        for link in [".claude/rules/harness/core.md", ".claude/rules/flutter/flutter.md", ".claude/rules/project/project.md",
                     ".claude/agents/planner.md", ".claude/skills/project-design", ".claude/skills/feature"]:
            self.assertTrue((r / link).is_symlink(), link)
            self.assertTrue((r / link).exists(), f"끊긴 링크: {link}")
        self.assertIn("my_app", (r / "AGENTS.md").read_text())
        self.assertIn("project-design", (r / "AGENTS.md").read_text())
        self.assertIn(".dart_tool/", (r / ".gitignore").read_text())
        self.assertEqual(self.p.run("git", "config", "core.hooksPath").stdout.strip(), ".harness/core/githooks")

    def test_init_is_idempotent_and_keeps_project_files(self):
        self.p.write(".harness/rules/project.md", "---\ndescription: x\n---\n# 내 프로젝트\n")
        self.p.harness("init")
        self.assertIn("내 프로젝트", (self.p.root / ".harness/rules/project.md").read_text())

    def test_check_rules_passes_after_init(self):
        self.assertIn("통과", self.p.harness("check-rules").stdout)

    def test_check_rules_detects_drift_and_sync_fixes(self):
        (self.p.root / ".claude/skills/feature").unlink()
        self.p.write(".harness/rules/architecture.md", '---\ndescription: 구조\npaths:\n  - "lib/**"\n---\n# 구조\n')
        r = self.p.harness("check-rules", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(".claude/skills/feature 링크가 없습니다", r.stdout)
        self.assertIn("architecture.md 링크가 없습니다", r.stdout)
        self.assertIn("AGENTS.md 의 규칙", r.stdout)
        self.assertIn("맞는 파일이 하나도 없습니다", r.stdout)
        self.p.harness("sync")
        self.p.write("lib/main.dart", "void main() {}\n")
        self.assertEqual(self.p.harness("check-rules", check=False).returncode, 0)
        self.assertIn("architecture.md", (self.p.root / "AGENTS.md").read_text())

    def test_check_rules_rejects_copies(self):
        self.p.write(".claude/rules/extra.md", "# 사본\n")
        self.p.write(".cursorrules", "x")
        out = self.p.harness("check-rules", check=False).stdout
        self.assertIn("extra.md 는 사본", out)
        self.assertIn(".cursorrules", out)

    def test_project_skill_overrides_core(self):
        self.p.write(".harness/skills/feature/SKILL.md", "---\nname: feature\ndescription: 프로젝트 전용\n---\n# x\n")
        self.p.harness("sync")
        target = (self.p.root / ".claude/skills/feature").resolve()
        self.assertEqual(target, (self.p.root / ".harness/skills/feature").resolve())


class CheckCodeTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.p.harness("init", "flutter")
        self.assertEqual(self.p.commit("chore: 하네스 설치").returncode, 0)

    def tearDown(self):
        self.p.tmp.cleanup()

    def check(self):
        return self.p.harness("check-code", check=False)

    def test_clean_change_passes(self):
        self.p.write("lib/a.dart", "int add(int a, int b) => a + b;\n")
        self.assertEqual(self.check().returncode, 0)

    def test_detects_secrets_logging_and_sensitive_log(self):
        self.p.write("lib/a.dart", 'void f() {\n  print("x");\n  logger.i("t=$accessToken");\n  logger.i("has=${token != null}");\n}\n')
        self.p.write("lib/k.dart", 'const k = "AKIA' + "ABCDEFGHIJKLMNOP" + '";\n')
        self.p.write("env/dev.json", "{}")
        self.p.write("env/dev.example.json", "{}")
        self.p.write("android/key.properties", "x")
        out = self.check().stdout
        self.assertIn("[logging] lib/a.dart:2", out)
        self.assertIn("[sensitive-log] lib/a.dart:3", out)
        self.assertNotIn("lib/a.dart:4", out)  # 상태만 남기는 로그는 허용
        self.assertIn("[secret-value] lib/k.dart:1", out)
        self.assertNotIn("env/dev.json", out)  # init 이 gitignore 에 넣었다
        self.assertIn("[secret-file] android/key.properties", out)
        self.assertNotIn("dev.example.json", out)

    def test_force_added_secret_is_caught_when_staged(self):
        self.p.write("env/dev.json", "{}")
        self.p.run("git", "add", "-f", "env/dev.json")
        self.assertIn("[secret-file] env/dev.json", self.p.harness("check-code", "--staged", check=False).stdout)

    def test_layers_from_config(self):
        cfg = json.loads((self.p.root / ".harness/config.json").read_text())
        cfg["layers"] = [{"files": "lib/features/**/domain/**", "forbid": ["package:flutter/material.dart", "/data/"],
                          "message": "domain 은 UI · data 를 모른다"}]
        (self.p.root / ".harness/config.json").write_text(json.dumps(cfg))
        self.p.write("lib/features/todo/domain/todo.dart", "import 'package:flutter/material.dart';\nclass Todo {}\n")
        self.p.write("lib/features/todo/presentation/todo_screen.dart", "import 'package:flutter/material.dart';\n")
        out = self.check().stdout
        self.assertIn("[layer] lib/features/todo/domain/todo.dart:1", out)
        self.assertNotIn("todo_screen.dart", out)

    def test_existing_violations_are_not_counted(self):
        self.p.write("lib/old.dart", 'void f() { print("old"); }\n')
        self.p.commit("chore: old", verify=False)  # 하네스 도입 전 코드라고 가정
        self.p.write("lib/old.dart", 'void f() { print("old"); }\nint g() => 1;\n')
        self.assertEqual(self.p.harness("check-code", "--base", "HEAD", check=False).returncode, 0)

    # ── 설정 값 리터럴 (config-literal) — 코드 · 테스트가 같은 상수를 쓰는지 ──

    def enable_config_literals(self):
        cfg = json.loads((self.p.root / ".harness/config.json").read_text())
        cfg["config_literals"] = {"enabled": True}
        (self.p.root / ".harness/config.json").write_text(json.dumps(cfg))

    CONFIG_LITERAL_CODE = (
        "Dio dio() => Dio(BaseOptions(\n"
        "  connectTimeout: const Duration(seconds: 10),\n"   # 2: 잡음 — 설정에 리터럴
        "  receiveTimeout: NetworkTimeouts.receive,\n"
        "));\n"
    )

    def test_config_literal_is_off_by_default(self):
        self.p.write("lib/core/network/dio.dart", self.CONFIG_LITERAL_CODE)
        self.assertNotIn("[config-literal]", self.check().stdout)

    def test_config_literal_in_code(self):
        self.enable_config_literals()
        self.p.write("lib/core/network/dio.dart", self.CONFIG_LITERAL_CODE)
        self.p.write("lib/core/constants/network_constants.dart",
                     "abstract final class NetworkTimeouts {\n"
                     "  static const Duration connect = Duration(seconds: 10);\n"  # 상수 선언 — 허용
                     "  static const receive = Duration(seconds: 10);\n"
                     "}\n"
                     "const debounce = Duration(milliseconds: 300);\n"
                     "final startedAt = Duration.zero;\n")
        self.p.write("lib/a.g.dart", "final x = f(const Duration(seconds: 1));\n")  # 생성 파일 — 허용
        self.p.write("lib/b.dart", "// 예: connectTimeout: Duration(seconds: 3)\nvoid f() {}\n")  # 주석 — 허용
        out = self.check().stdout
        self.assertIn("[config-literal] lib/core/network/dio.dart:2", out)
        self.assertEqual(out.count("[config-literal]"), 1, out)

    def test_config_literal_in_test_expectations(self):
        self.enable_config_literals()
        self.p.write("test/core/network/dio_test.dart",
                     "void main() {\n"
                     "  expect(dio.options.connectTimeout, const Duration(seconds: 10));\n"  # 2: 잡음
                     "  expect(\n"
                     "    dio.options.receiveTimeout,\n"
                     "    const Duration(seconds: 10),\n"                                    # 5: 잡음 (여러 줄 expect)
                     "  );\n"
                     "  expect(dio.options.sendTimeout, NetworkTimeouts.send);\n"            # 상수 참조 — 허용
                     "  expect(parseDuration('1s'), const Duration(seconds: 1));\n"          # 동작 결과 — 허용
                     "  final e = DioException.connectionTimeout(\n"
                     "    timeout: const Duration(seconds: 10),\n"                            # 가짜 예외 인자 — 허용
                     "  );\n"
                     "}\n")
        out = self.check().stdout
        self.assertIn("[config-literal] test/core/network/dio_test.dart:2", out)
        self.assertIn("[config-literal] test/core/network/dio_test.dart:5", out)
        self.assertEqual(out.count("[config-literal]"), 2, out)

    def test_config_literal_ignores_existing_lines(self):
        self.p.write("lib/core/network/dio.dart", self.CONFIG_LITERAL_CODE)
        self.p.commit("chore: old", verify=False)  # 검사를 켜기 전 코드
        self.enable_config_literals()
        self.p.write("lib/core/network/dio.dart", self.CONFIG_LITERAL_CODE + "int g() => 1;\n")
        self.assertNotIn("[config-literal]", self.p.harness("check-code", "--base", "HEAD", check=False).stdout)

    def test_project_checks_module(self):
        self.p.write(".harness/checks.py",
                     "def check(ctx):\n"
                     "    for path, lines in ctx.added.items():\n"
                     "        for no, text in lines:\n"
                     "            if 'Colors.' in text:\n"
                     "                ctx.report('raw-color', path, no, '테마 색을 쓴다', '.harness/rules/ui.md')\n")
        self.p.write("lib/w.dart", "final c = Colors.red;\n")
        self.assertIn("[raw-color] lib/w.dart:1", self.check().stdout)

    def test_git_hooks(self):
        self.p.write("lib/a.dart", 'void f() { print("x"); }\n')
        r = self.p.commit("feat: a")
        self.assertNotEqual(r.returncode, 0, "pre-commit 이 print 를 막아야 한다")
        self.p.write("lib/a.dart", "int f() => 1;\n")
        self.assertNotEqual(self.p.commit("bad message").returncode, 0, "commit-msg 가 형식을 막아야 한다")
        self.assertEqual(self.p.commit("feat: a").returncode, 0)

    def test_post_edit_and_stop_hooks(self):
        self.p.write("lib/a.dart", 'void f() { print("x"); }\n')
        r = self.p.hook("post_edit", {"tool_input": {"file_path": str(self.p.root / "lib/a.dart")}})
        self.assertEqual(r.returncode, 2)
        self.assertIn("[logging]", r.stderr)
        self.assertEqual(self.p.hook("post_edit", {"tool_input": {"file_path": str(self.p.root / "README.md")}}).returncode, 0)
        stop = json.loads(self.p.hook("stop", {}).stdout)
        self.assertEqual(stop["decision"], "block")
        self.assertEqual(self.p.hook("stop", {"stop_hook_active": True}).stdout.strip(), "")


class PreToolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project()
        cls.p.harness("init", "flutter")

    @classmethod
    def tearDownClass(cls):
        cls.p.tmp.cleanup()

    def bash(self, command):
        return self.p.decision({"tool_name": "Bash", "tool_input": {"command": command}})

    def edit(self, rel):
        return self.p.decision({"tool_name": "Edit", "tool_input": {"file_path": str(self.p.root / rel)}})

    def test_bash(self):
        cases = {
            "git push --force origin feat/a": "deny",
            "git push origin main": "deny",
            "git push origin HEAD:main": "deny",
            "git reset --hard HEAD~1": "deny",
            "gh pr merge 3": "deny",
            "fastlane ios beta": "deny",
            "git push -u origin feat/a": "ask",
            "gh pr create --fill": "ask",
            "flutter pub add dio": "ask",
            "git submodule update --remote": "ask",
            "flutter test test/a_test.dart": "allow",
            "git status": "allow",
            "grep -r fastlane docs": "allow",
        }
        for command, expected in cases.items():
            self.assertEqual(self.bash(command), expected, command)

    def test_files(self):
        cases = {
            ".harness/core/rules/core.md": "deny",
            "env/prod.json": "deny",
            "android/key.properties": "deny",
            "android/app/upload.jks": "deny",
            "env/prod.example.json": "allow",
            "lib/a.g.dart": "ask",
            "pubspec.yaml": "ask",
            ".github/workflows/ci.yml": "ask",
            ".harness/config.json": "ask",
            ".claude/settings.json": "ask",
            "lib/a.dart": "allow",
            ".harness/rules/architecture.md": "allow",
        }
        for rel, expected in cases.items():
            self.assertEqual(self.edit(rel), expected, rel)

    def test_protected_branches_from_config(self):
        cfg_path = self.p.root / ".harness/config.json"
        original = cfg_path.read_text()
        cfg = json.loads(original)
        cfg["protected_branches"] = ["main", "dev"]
        cfg_path.write_text(json.dumps(cfg))
        try:
            self.assertEqual(self.bash("git push origin dev"), "deny")
        finally:
            cfg_path.write_text(original)


class SubmoduleTest(unittest.TestCase):
    """실제 서브모듈로 설치했을 때: 공유 하네스를 프로젝트 안에서 고치면 구성 검사가 잡는다."""

    def test_dirty_core_is_detected(self):
        p = Project()
        try:
            core = p.root / ".harness/core"
            for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "chore: core"]):
                subprocess.run(["git", "-C", str(core), *args], check=True, capture_output=True, env=ENV)
            p.harness("init", "flutter")
            self.assertEqual(p.harness("check-rules", check=False).returncode, 0)
            (core / "rules/core.md").write_text("바뀜")
            out = p.harness("check-rules", check=False).stdout
            self.assertIn("공유 하네스(.harness/core)가 프로젝트 안에서 수정됐습니다", out)
        finally:
            p.tmp.cleanup()


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=GIT_FILE_ENV).stdout.strip()


# 로컬 경로 서브모듈(file://)을 허용 — 테스트에서만
GIT_FILE_ENV = {**ENV, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "protocol.file.allow", "GIT_CONFIG_VALUE_0": "always"}


class ReleaseBranchTest(unittest.TestCase):
    """서브모듈은 release 브랜치만 따라간다 — main 의 개발 커밋은 업데이트 대상이 아니다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        # 가짜 템플릿 원격: 지금 작업 트리 = v0.1.0 (release), 그 뒤 main 에 개발 커밋
        self.src = base / "template"
        shutil.copytree(TEMPLATE, self.src, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        (self.src / "VERSION").write_text("0.1.0\n")
        _git(self.src, "init", "-q", "-b", "main")
        _git(self.src, "add", "-A")
        _git(self.src, "commit", "-q", "-m", "release 0.1.0")
        _git(self.src, "tag", "v0.1.0")
        _git(self.src, "branch", "release")
        (self.src / "README.md").write_text("개발 중\n")
        _git(self.src, "commit", "-qam", "개발 중 커밋")
        self.dev_commit = _git(self.src, "rev-parse", "HEAD")
        self.release_commit = _git(self.src, "rev-parse", "v0.1.0")
        # 프로젝트: 문서대로 -b release 로 추가
        self.app = base / "app"
        self.app.mkdir()
        _git(self.app, "init", "-q", "-b", "main")
        _git(self.app, "submodule", "add", "-q", "-b", "release", str(self.src), ".harness/core")

    def tearDown(self):
        self.tmp.cleanup()

    def harness(self, *args):
        return subprocess.run([sys.executable, ".harness/core/scripts/harness.py", *args], cwd=self.app,
                              capture_output=True, text=True, env=GIT_FILE_ENV)

    def core_head(self):
        return _git(self.app / ".harness/core", "rev-parse", "HEAD")

    def test_submodule_tracks_release_not_main(self):
        self.assertEqual(self.core_head(), self.release_commit)
        self.harness("init", "flutter")
        self.assertEqual(_git(self.app, "config", "-f", ".gitmodules", "submodule..harness/core.branch"), "release")
        out = self.harness("update").stdout
        self.assertIn("이미 최신 릴리스", out)
        self.assertEqual(self.core_head(), self.release_commit, "main 의 개발 커밋을 받으면 안 된다")

    def test_update_picks_new_release(self):
        self.harness("init", "flutter")
        _git(self.app, "add", "-A")
        _git(self.app, "commit", "-q", "--no-verify", "-m", "chore: 하네스 설치")
        (self.src / "VERSION").write_text("0.2.0\n")
        _git(self.src, "commit", "-qam", "release 0.2.0")
        _git(self.src, "tag", "v0.2.0")
        _git(self.src, "branch", "-f", "release", "v0.2.0")
        r = self.harness("update")
        self.assertIn("하네스 0.1.0 → 0.2.0", r.stdout, r.stdout + r.stderr)
        self.assertEqual(self.core_head(), _git(self.src, "rev-parse", "v0.2.0"))

    def test_init_adds_branch_when_submodule_added_without_it(self):
        _git(self.app, "config", "-f", ".gitmodules", "--unset", "submodule..harness/core.branch")
        out = self.harness("init", "flutter").stdout
        self.assertIn("branch = release", out)
        self.assertEqual(_git(self.app, "config", "-f", ".gitmodules", "submodule..harness/core.branch"), "release")


class UpgradeCompatibilityTest(unittest.TestCase):
    """이전 정식 릴리스(최신 v* 태그)로 설치한 프로젝트를 지금 작업 트리로 올려도 sync 후 구성 검사가 통과한다."""

    def test_upgrade_from_previous_release(self):
        tags = subprocess.run(["git", "-C", str(TEMPLATE), "tag", "--list", "v*", "--sort=-v:refname"],
                              capture_output=True, text=True).stdout.split()
        if not tags:
            self.skipTest("이전 릴리스 태그가 없다 (첫 릴리스 전)")
        prev = tags[0]
        p = Project()
        try:
            core = p.root / ".harness/core"
            shutil.rmtree(core)
            core.mkdir(parents=True)
            archive = subprocess.run(["git", "-C", str(TEMPLATE), "archive", prev], capture_output=True, check=True).stdout
            subprocess.run(["tar", "-x", "-C", str(core)], input=archive, check=True)
            p.harness("init", "flutter")
            p.write(".harness/rules/project.md", "---\ndescription: 내 프로젝트\n---\n# 내 프로젝트\n")
            p.write("lib/main.dart", "void main() {}\n")
            p.write(".harness/rules/architecture.md", '---\ndescription: 구조\npaths:\n  - "lib/**"\n---\n# 구조\n')
            p.harness("sync")
            self.assertEqual(p.commit("chore: 이전 릴리스로 설치", verify=False).returncode, 0)
            # 지금 버전으로 교체 (= 업데이트 PR 이 서브모듈 포인터를 바꾼 상태)
            shutil.rmtree(core)
            shutil.copytree(TEMPLATE, core, ignore=shutil.ignore_patterns(".git", "__pycache__", "tests"))
            p.harness("sync")
            r = p.harness("check-rules", check=False)
            self.assertEqual(r.returncode, 0, f"{prev} → 지금 업그레이드 후 구성 검사 실패\n{r.stdout}")
            self.assertIn("내 프로젝트", (p.root / ".harness/rules/project.md").read_text())
            self.assertEqual(p.harness("check-code", "--base", "HEAD", check=False).returncode, 0)
        finally:
            p.tmp.cleanup()


class ReleaseScriptTest(unittest.TestCase):
    """scripts/release.py — main 커밋 분석 → VERSION · CHANGELOG · 태그 · release 이동 (main 은 건드리지 않는다)"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.origin = base / "origin.git"
        _git(base, "init", "-q", "--bare", str(self.origin))
        self.work = base / "work"
        self.work.mkdir()
        _git(self.work, "init", "-q", "-b", "main")
        (self.work / "VERSION").write_text("0.1.0\n")
        (self.work / "CHANGELOG.md").write_text("# 변경 기록\n\n## 0.1.0 — 2026-11-20\n\n- 첫 릴리스\n")
        self.commit("feat: 첫 릴리스")
        _git(self.work, "tag", "-a", "v0.1.0", "-m", "0.1.0")
        _git(self.work, "remote", "add", "origin", str(self.origin))
        _git(self.work, "push", "-q", "origin", "main", "main:refs/heads/release", "v0.1.0")

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, subject, body=""):
        (self.work / "f.txt").write_text(subject)
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-q", "-m", subject + (f"\n\n{body}" if body else ""))
        _git(self.work, "push", "-q", "origin", "HEAD:main") if (self.work / ".git/refs/remotes/origin").exists() else None
        return _git(self.work, "rev-parse", "HEAD")

    def release(self, *extra):
        _git(self.work, "fetch", "-q", "--tags", "origin")
        r = subprocess.run([sys.executable, str(TEMPLATE / "scripts/release.py"), "--main", "HEAD", *extra],
                           cwd=self.work, capture_output=True, text=True, env=GIT_FILE_ENV)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        _git(self.work, "fetch", "-q", "--tags", "origin")
        return r.stdout

    def show(self, path):
        return _git(self.work, "show", f"origin/release:{path}")

    def test_bumps_and_skips(self):
        self.commit("docs: README 정리 (#2)")
        self.commit("test: 테스트 추가")
        self.assertIn("릴리스 없음", self.release())
        self.assertEqual(self.show("VERSION"), "0.1.0")

        main_sha = self.commit("fix: 오탐 수정 (#3)")
        out = self.release()
        self.assertIn("0.1.0 → 0.1.1 (patch)", out)
        self.assertEqual(self.show("VERSION"), "0.1.1")
        log = self.show("CHANGELOG.md")
        self.assertIn("## 0.1.1", log)
        self.assertIn("- fix: 오탐 수정 (#3)", log)
        self.assertIn("- docs: README 정리 (#2)", log)  # 기타로 기록
        self.assertIn("## 0.1.0", log)
        self.assertLess(log.index("## 0.1.1"), log.index("## 0.1.0"))
        parents = _git(self.work, "log", "-1", "--format=%P", "origin/release").split()
        self.assertIn(main_sha, parents)
        self.assertEqual(_git(self.work, "rev-parse", "v0.1.1^{commit}"), _git(self.work, "rev-parse", "origin/release"))
        self.assertEqual(_git(self.work, "rev-parse", "origin/main"), main_sha, "main 은 바뀌지 않는다")

        self.assertIn("릴리스 없음", self.release())  # 같은 커밋 다시

        prev_release = _git(self.work, "rev-parse", "origin/release")
        self.commit("feat: 새 검사 (#4)")
        self.assertIn("0.1.1 → 0.2.0 (minor)", self.release())
        _git(self.work, "merge-base", "--is-ancestor", prev_release, "origin/release")  # fast-forward

        self.commit("feat!: 설정 키 변경")
        self.assertIn("0.2.0 → 0.3.0 (major)", self.release())  # 1.0 전에는 깨지는 변경도 minor 자리

    def test_manual_bump_and_dry_run(self):
        self.commit("chore: 정리")
        out = self.release("--bump", "patch", "--dry-run")
        self.assertIn("0.1.0 → 0.1.1", out)
        self.assertEqual(self.show("VERSION"), "0.1.0", "dry-run 은 push 하지 않는다")


FAKE_RUNNER = """
import re
from pathlib import Path


def run_tests(root, targets):
    # 가짜 실행기: 테스트의 'EXPECT <파일> <문자열>' — 파일이 없으면 load_error, 문자열이 없으면 fail
    root = Path(root)
    files = []
    for t in targets or ["test"]:
        p = root / t
        files += [x.relative_to(root).as_posix() for x in p.rglob("*_test.dart")] if p.is_dir() else [t]
    out = {}
    for t in files:
        status = "pass"
        for src, token in re.findall(r"EXPECT (\\S+) (\\S+)", (root / t).read_text()):
            if not (root / src).exists():
                status = "load_error"
                break
            if token not in (root / src).read_text():
                status = "fail"
        out[t] = status
    return out


def prepare(root):
    pass
"""

CHAT = "lib/features/chat/domain/chat.dart"
CHAT_TEST = "test/features/chat/domain/chat_test.dart"
PAY = "lib/features/pay/domain/pay.dart"


class TddGuardTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.p.harness("init", "flutter")
        self.p.write("pubspec.yaml", "name: my_app\n")
        self.p.write(".harness/checks.py", FAKE_RUNNER)
        cfg = json.loads((self.p.root / ".harness/config.json").read_text())
        cfg["tdd"] = {"enabled": True, "paths": ["lib/features/**/domain/**"]}
        (self.p.root / ".harness/config.json").write_text(json.dumps(cfg))
        self.p.write(PAY, "int pay() => 1;\n")
        self.assertEqual(self.p.commit("chore: 설치", verify=False).returncode, 0)

    def tearDown(self):
        self.p.tmp.cleanup()

    def edit(self, rel):
        return self.p.decision({"tool_name": "Write", "tool_input": {"file_path": str(self.p.root / rel)}})

    def test(self, *targets):
        return self.p.harness("test", *targets, check=False)

    def write_chat_test(self, token="send"):
        self.p.write(CHAT_TEST, f"// EXPECT {CHAT} {token}\nimport 'package:my_app/features/chat/domain/chat.dart';\n")

    def tdd_problems(self):
        out = self.p.harness("check-code", "--base", "HEAD", check=False).stdout
        return [l for l in out.splitlines() if "[tdd]" in l]

    def test_disabled_guard_allows_everything(self):
        cfg = json.loads((self.p.root / ".harness/config.json").read_text())
        cfg["tdd"]["enabled"] = False
        (self.p.root / ".harness/config.json").write_text(json.dumps(cfg))
        self.assertEqual(self.edit(CHAT), "allow")
        self.p.write(CHAT, "x")
        self.assertEqual(self.tdd_problems(), [])

    def test_full_cycle(self):
        # ① 테스트 없이 기능 코드 → 차단, 테스트 · 대상 밖 파일은 허용
        self.assertEqual(self.edit(CHAT), "deny")
        self.assertEqual(self.edit(CHAT_TEST), "allow")
        self.assertEqual(self.edit("lib/features/chat/presentation/chat_screen.dart"), "allow")
        # ② 테스트 작성 → 실행 → 컴파일 실패 RED → 잠금 해제
        self.write_chat_test()
        self.assertNotEqual(self.test(CHAT_TEST).returncode, 0)
        self.assertEqual(self.edit(CHAT), "allow")
        # ③ 골격만 → 완료 아님 (컴파일 실패만 봤다)
        self.p.write(CHAT, "void stub() {}\n")
        self.assertTrue(any("컴파일 실패(RED)만" in l for l in self.tdd_problems()), self.tdd_problems())
        # ④ 골격 상태로 실행 → behavior RED → 구현 → GREEN → 완료
        self.assertNotEqual(self.test(CHAT_TEST).returncode, 0)
        self.assertTrue(any("RED 뒤 GREEN 이 없다" in l for l in self.tdd_problems()))
        self.p.write(CHAT, "void send() {}\n")
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        self.assertEqual(self.tdd_problems(), [])
        # ⑤ GREEN 뒤에 코드가 바뀌면 다시 확인해야 한다
        self.p.write(CHAT, "void send() {}\n// 바뀜\n")
        self.assertTrue(any("GREEN 이후" in l for l in self.tdd_problems()))
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        self.assertEqual(self.tdd_problems(), [])
        # ⑥ 커밋 (pre-commit 통과) → 기록 초기화 → 다음 변경은 다시 RED 필요
        self.assertEqual(self.p.commit("feat: 채팅 보내기").returncode, 0)
        self.assertEqual(self.edit(CHAT), "deny")

    # ── RED 이후 구현이 바뀌어야 GREEN (테스트만 고쳐 통과시키기 차단) ──

    def test_fixing_only_the_test_is_not_red_to_green(self):
        # 구현을 먼저 썼다 (셸 등) → 틀린 기대값으로 실패 → 테스트만 고쳐 통과
        self.p.write(CHAT, "void send() {}\n")
        self.write_chat_test("sned")
        self.assertNotEqual(self.test(CHAT_TEST).returncode, 0)
        self.write_chat_test("send")
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        self.assertTrue(any("RED 이후 구현이 바뀌지 않았다" in l for l in self.tdd_problems()), self.tdd_problems())
        # 구현에 주석만 더해도 지금 테스트로 실패한 적이 없으므로 여전히 미완료
        self.p.write(CHAT, "void send() {}\n// 주석\n")
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        self.assertTrue(any("RED 이후 구현이 바뀌지 않았다" in l for l in self.tdd_problems()), self.tdd_problems())

    def test_test_written_after_code_is_not_red_to_green(self):
        self.p.write(CHAT, "void send() {}\n")
        self.write_chat_test("send")
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        self.assertTrue(any("RED 미확인" in l for l in self.tdd_problems()), self.tdd_problems())

    def test_refining_test_after_red_then_rerun_completes(self):
        # 정상 흐름: RED → 테스트를 다듬음 → 다시 실행해 RED 확인 → 구현 → GREEN
        self.write_chat_test("send")
        self.test(CHAT_TEST)                              # load_error
        self.p.write(CHAT, "void stub() {}\n")
        self.assertNotEqual(self.test(CHAT_TEST).returncode, 0)  # fail (골격)
        self.p.write(CHAT_TEST, f"// EXPECT {CHAT} send\n// EXPECT {CHAT} receive\nimport 'package:my_app/features/chat/domain/chat.dart';\n")
        self.assertNotEqual(self.test(CHAT_TEST).returncode, 0)  # 바뀐 테스트로 다시 RED
        self.p.write(CHAT, "void send() {}\nvoid receive() {}\n")
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        self.assertEqual(self.tdd_problems(), [])

    def test_changing_test_after_red_needs_red_again(self):
        self.write_chat_test("send")
        self.p.write(CHAT, "void stub() {}\n")
        self.assertNotEqual(self.test(CHAT_TEST).returncode, 0)  # fail (골격, 테스트 v1)
        self.p.write(CHAT_TEST, f"// EXPECT {CHAT} send\n// 바뀐 테스트\nimport 'package:my_app/features/chat/domain/chat.dart';\n")
        self.p.write(CHAT, "void send() {}\n")
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)     # 테스트 v2 로는 실패한 적이 없다
        self.assertTrue(any("RED 이후 구현이 바뀌지 않았다" in l for l in self.tdd_problems()), self.tdd_problems())

    def test_import_only_change_after_green_completes(self):
        # 정상 흐름: GREEN 뒤 공용 타입을 옮겨 테스트의 import 줄만 바뀜 (본문 · 검증 그대로, 구현 불변)
        body = f"// EXPECT {CHAT} send\n"
        self.p.write(CHAT_TEST, body + "import 'package:my_app/features/chat/domain/chat.dart';\n")
        self.p.write(CHAT, "void stub() {}\n")
        self.assertNotEqual(self.test(CHAT_TEST).returncode, 0)
        self.p.write(CHAT, "void send() {}\n")
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        self.p.write(CHAT_TEST, body + "import 'package:my_app/features/chat/domain/chat.dart';\n"
                                       "import 'package:collection/collection.dart';\n")
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        self.assertEqual(self.tdd_problems(), [])

    def test_body_change_after_green_without_red_is_blocked(self):
        # 본문(검증)이 바뀌었는데 그 테스트로 RED 를 본 적이 없으면 미완료 — import 무시가 우회로가 되지 않는다
        imports = "import 'package:my_app/features/chat/domain/chat.dart';\n"
        self.p.write(CHAT_TEST, f"// EXPECT {CHAT} send\n" + imports)
        self.p.write(CHAT, "void stub() {}\n")
        self.assertNotEqual(self.test(CHAT_TEST).returncode, 0)
        self.p.write(CHAT, "void send() {}\nvoid sendAll() {}\n")
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        self.p.write(CHAT_TEST, f"// EXPECT {CHAT} sendAll\n" + imports)  # 이미 있는 동작으로 기대를 바꿈
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        # 다시 실행해도 풀리지 않으므로 "다시 통과를 확인" 이 아니라 RED 가 없다는 사실을 알린다
        self.assertTrue(any(CHAT in l and "RED 이후 구현이 바뀌지 않았다" in l for l in self.tdd_problems()),
                        self.tdd_problems())

    def test_formatting_test_after_red_still_completes(self):
        # 정상 흐름: RED 뒤 테스트에 포맷(공백 · 줄바꿈)만 적용하고 구현 → GREEN
        self.write_chat_test("send")
        self.test(CHAT_TEST)                                     # load_error
        self.p.write(CHAT, "void stub() {}\n")
        self.assertNotEqual(self.test(CHAT_TEST).returncode, 0)  # fail
        self.p.write(CHAT_TEST, f"// EXPECT {CHAT} send\n\n\nimport   'package:my_app/features/chat/domain/chat.dart';\n\n")
        self.p.write(CHAT, "void send() {}\n")
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        self.assertEqual(self.tdd_problems(), [])

    def test_declaration_file_completes_when_linked_impl_changed_in_cycle(self):
        # 정상 흐름: 동작 없는 선언 파일(모델 · 인터페이스)은 골격이 곧 완성본 — 같은 사이클에서 연결된 구현이 바뀌면 완료
        model = "lib/features/chat/domain/chat_model.dart"
        self.p.write(CHAT_TEST, f"// EXPECT {CHAT} send\n"
                                "import 'package:my_app/features/chat/domain/chat.dart';\n"
                                "import 'package:my_app/features/chat/domain/chat_model.dart';\n")
        self.test(CHAT_TEST)                                     # load_error
        self.p.write(model, "class ChatModel {}\n")
        self.p.write(CHAT, "void stub() {}\n")
        self.assertNotEqual(self.test(CHAT_TEST).returncode, 0)  # fail (모델 완성 · 구현 골격)
        self.p.write(CHAT, "void send() {}\n")
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        self.assertEqual(self.tdd_problems(), [])

    def test_declaration_file_with_only_test_fixed_is_still_blocked(self):
        # 선언 파일이 있어도, 구현이 하나도 바뀌지 않고 테스트만 고쳐 통과하면 미완료
        model = "lib/features/chat/domain/chat_model.dart"
        self.p.write(model, "class ChatModel {}\n")
        self.p.write(CHAT, "void send() {}\n")
        imports = ("import 'package:my_app/features/chat/domain/chat.dart';\n"
                   "import 'package:my_app/features/chat/domain/chat_model.dart';\n")
        self.p.write(CHAT_TEST, f"// EXPECT {CHAT} sned\n" + imports)
        self.assertNotEqual(self.test(CHAT_TEST).returncode, 0)
        self.p.write(CHAT_TEST, f"// EXPECT {CHAT} send\n" + imports)
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        problems = self.tdd_problems()
        self.assertTrue(any(CHAT in l and "RED 이후 구현이 바뀌지 않았다" in l for l in problems), problems)
        self.assertTrue(any(model in l and "RED 이후 구현이 바뀌지 않았다" in l for l in problems), problems)

    def test_records_from_previous_version_still_complete(self):
        # 업데이트 전 기록(테스트 모양 해시 없음)으로 끝낸 사이클도 그대로 완료로 인정한다
        self.write_chat_test("send")
        self.p.write(CHAT, "void stub() {}\n")
        self.test(CHAT_TEST)
        self.p.write(CHAT, "void send() {}\n")
        self.test(CHAT_TEST)
        state_file = self.p.root / ".harness/out/tdd.json"
        state = json.loads(state_file.read_text())
        for run in state["runs"]:
            run.pop("shapes", None)
            run.pop("bodies", None)
        state_file.write_text(json.dumps(state))
        self.assertEqual(self.tdd_problems(), [])

    # ── Bash 로 대상 코드를 쓰면 바로 알린다 (명령 전후 비교) ──

    def bash(self, command, tid="t1", pre=True):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "tool_use_id": tid}
        if pre:
            self.assertEqual(self.p.decision(payload), "allow")
        self.p.run("sh", "-c", command)
        return self.p.hook("post_edit", payload)

    def bash_dir(self):
        d = self.p.root / ".harness/out/bash"
        return sorted(x.name for x in d.iterdir()) if d.exists() else []

    def assert_caught(self, r, rel):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("[TDD Guard]", r.stderr)
        self.assertIn(rel, r.stderr)

    def test_bash_write_without_red_is_caught(self):
        self.assert_caught(self.bash(f"mkdir -p $(dirname {CHAT}) && cat > {CHAT} <<'EOF'\nvoid send() {{}}\nEOF"), CHAT)
        self.assertEqual(self.bash_dir(), [], "명령마다 쓴 비교 파일은 끝나면 지운다")

    def test_bash_edit_of_committed_file_is_caught(self):
        self.assert_caught(self.bash(f"sed -i.bak 's/1/2/' {PAY} && rm {PAY}.bak"), PAY)

    def test_bash_move_and_copy_keeping_mtime_are_caught(self):
        # 수정 시각을 보존하는 mv · cp -p 도 잡는다 (시각 기반 감지의 빈틈)
        self.p.write("tmp_chat.dart", "void send() {}\n")
        self.p.write("tmp_pay.dart", "int pay() => 5;\n")
        os.utime(self.p.root / "tmp_chat.dart", (1, 1))
        os.utime(self.p.root / "tmp_pay.dart", (1, 1))
        self.assert_caught(self.bash(f"mkdir -p $(dirname {CHAT}) && mv tmp_chat.dart {CHAT}"), CHAT)
        self.assert_caught(self.bash(f"cp -p tmp_pay.dart {PAY}", tid="t2"), PAY)

    def test_bash_write_after_red_is_allowed(self):
        self.write_chat_test()
        self.test(CHAT_TEST)
        r = self.bash(f"mkdir -p $(dirname {CHAT}) && echo 'void send() {{}}' > {CHAT}")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_bash_writes_outside_guard_are_allowed(self):
        for i, cmd in enumerate([
            f"mkdir -p $(dirname {CHAT_TEST}) && echo '// t' > {CHAT_TEST}",               # 테스트
            "mkdir -p lib/features/chat/presentation && echo 'x' > lib/features/chat/presentation/chat_screen.dart",  # 대상 밖
            "mkdir -p lib/features/chat/domain && echo 'x' > lib/features/chat/domain/chat.g.dart",                  # 생성 파일
            "echo '# doc' > README.md",
            "git status --short",                                                          # 읽기 전용
            f"rm {PAY}",                                                                   # 삭제는 우회가 아니다
        ]):
            r = self.bash(cmd, tid=f"t{i}")
            self.assertEqual(r.returncode, 0, f"{cmd}\n{r.stderr}")
        self.assertEqual(self.bash_dir(), [])

    def test_bash_does_not_blame_files_dirty_before_the_command(self):
        self.p.write(CHAT, "void send() {}\n")  # 명령 전부터 고쳐져 있던 파일 (사람 · 다른 도구)
        r = self.bash("echo '# doc' > README.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.tdd_problems(), "완료 검사는 그대로 잡는다")

    def test_bash_without_pre_snapshot_falls_back_to_all_dirty_files(self):
        r = self.bash(f"mkdir -p $(dirname {CHAT}) && echo 'void send() {{}}' > {CHAT}", pre=False)
        self.assert_caught(r, CHAT)

    def test_bash_check_is_off_when_guard_disabled(self):
        cfg = json.loads((self.p.root / ".harness/config.json").read_text())
        cfg["tdd"]["enabled"] = False
        (self.p.root / ".harness/config.json").write_text(json.dumps(cfg))
        r = self.bash(f"mkdir -p $(dirname {CHAT}) && echo 'void send() {{}}' > {CHAT}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.bash_dir(), [], "꺼져 있으면 비교 파일도 만들지 않는다")

    def test_post_tool_hook_covers_bash(self):
        settings = json.loads((self.p.root / ".claude/settings.json").read_text())
        matchers = [m.get("matcher", "") for m in settings["hooks"]["PostToolUse"]]
        self.assertTrue(any("Bash" in m.split("|") for m in matchers), matchers)

    # ── 기능 브랜치에서 여러 번 나눠 커밋 ──

    def test_committed_cycle_on_feature_branch_stays_complete(self):
        # 정상 흐름: 기능 브랜치에서 사이클 → 커밋(pre-commit 통과) → 다음 작업 중 verify — 이미 커밋한 파일을 다시 막지 않는다
        self.p.run("git", "switch", "-q", "-c", "feat/chat")
        self.write_chat_test("send")
        self.p.write(CHAT, "void stub() {}\n")
        self.assertNotEqual(self.test(CHAT_TEST).returncode, 0)
        self.p.write(CHAT, "void send() {}\n")
        self.assertEqual(self.test(CHAT_TEST).returncode, 0)
        self.assertEqual(self.p.commit("feat: 채팅 보내기").returncode, 0)
        self.p.write("README.md", "# 다음 작업\n")
        out = self.p.harness("check-code", "--base", "main", check=False).stdout
        self.assertNotIn("[tdd]", out)

    def test_uncommitted_change_after_commit_on_feature_branch_is_still_checked(self):
        # 커밋 뒤 RED 없이 다시 고친 대상 파일은 계속 잡는다
        self.p.run("git", "switch", "-q", "-c", "feat/chat")
        self.write_chat_test("send")
        self.p.write(CHAT, "void stub() {}\n")
        self.test(CHAT_TEST)
        self.p.write(CHAT, "void send() {}\n")
        self.test(CHAT_TEST)
        self.assertEqual(self.p.commit("feat: 채팅 보내기").returncode, 0)
        self.p.write(CHAT, "void send() {}\nvoid receive() {}\n")  # 훅 밖(셸 등)에서 고쳤다고 가정
        out = self.p.harness("check-code", "--base", "main", check=False).stdout
        self.assertIn(f"[tdd] {CHAT}", out)

    def test_red_of_other_feature_does_not_unlock(self):
        self.write_chat_test()
        self.test(CHAT_TEST)
        self.assertEqual(self.edit(CHAT), "allow")
        self.assertEqual(self.edit(PAY), "deny")

    def test_commit_blocked_without_cycle(self):
        self.p.write(PAY, "int pay() => 2;\n")  # 훅 밖(셸 등)에서 고쳤다고 가정
        r = self.p.commit("fix: 결제")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("[tdd]", r.stdout + r.stderr)

    def test_skip_needs_approval_and_is_bound_to_content(self):
        self.assertEqual(self.p.decision({"tool_name": "Bash", "tool_input": {"command": ".harness/core/harness tdd skip lib/x.dart --reason r"}}), "ask")
        self.assertEqual(self.edit(".harness/tdd-skip.json"), "ask")
        self.p.harness("tdd", "skip", PAY, "--reason", "리팩토링 — 동작 변화 없음")
        self.assertEqual(self.edit(PAY), "allow")
        self.assertEqual(self.tdd_problems(), [])
        self.p.write(PAY, "int pay() => 3;\n")
        self.assertTrue(any(PAY in l for l in self.tdd_problems()), "내용이 바뀌면 예외가 무효")

    def test_ci_reproduces_red_on_base(self):
        base = _git(self.p.root, "rev-parse", "HEAD")
        self.p.write(CHAT, "void send() {}\n")
        self.write_chat_test("receive")
        self.p.write(CHAT, "void send() {}\nvoid receive() {}\n")
        self.assertEqual(self.p.commit("feat: 받기", verify=False).returncode, 0)
        r = self.p.harness("tdd", "ci", "--base", base, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("RED 재현", r.stdout)

    def test_ci_rejects_test_that_passes_before_change(self):
        self.p.write(CHAT, "void send() {}\n")
        self.assertEqual(self.p.commit("chore: 기존 코드", verify=False).returncode, 0)
        base = _git(self.p.root, "rev-parse", "HEAD")
        self.write_chat_test("send")  # 이미 있는 동작 — 변경 전에도 통과
        self.p.write(CHAT, "void send() {}\n// 바꿈\n")
        self.p.commit("feat: 가짜 TDD", verify=False)
        out = self.p.harness("tdd", "ci", "--base", base, check=False).stdout
        self.assertIn("변경 전 코드에서도 통과", out)

    def test_ci_rejects_source_change_without_test(self):
        base = _git(self.p.root, "rev-parse", "HEAD")
        self.p.write(PAY, "int pay() => 9;\n")
        self.p.commit("fix: 결제", verify=False)
        out = self.p.harness("tdd", "ci", "--base", base, check=False).stdout
        self.assertIn("연결된 테스트 변경이 없다", out)


REQ_DOC = """# 채팅 요구사항

#### CHAT-REQ-001 — 채팅방 생성
#### CHAT-REQ-002 — 접근 권한
본문에서 언급만 하는 (CHAT-REQ-003) 은 정의가 아니다.
"""
TS_DOC = """# 채팅 시나리오

> 상태: 구현됨

| ID | 요구사항 | 시나리오 | 테스트 |
|----|----------|----------|--------|
| CHAT-TS-001 | CHAT-REQ-001 | 지원하면 채팅방이 생긴다 | api |
| CHAT-TS-002 | CHAT-REQ-002 | 제3자는 못 본다 | api |
"""
TEST_PY = """import pytest


@pytest.mark.scenario("CHAT-TS-001")
def test_create():
    pass


@pytest.mark.scenario("CHAT-TS-002")
def test_forbidden():
    pass
"""


class TraceabilityTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.p.harness("init", "flutter")
        cfg = json.loads((self.p.root / ".harness/config.json").read_text())
        cfg["trace"] = {"enabled": True, "requirement_docs": ["docs/specs/*.md"],
                        "scenario_docs": ["docs/domains/*/test-scenarios.md"], "tests": ["tests/**/test_*.py"],
                        "test_marker": "@pytest\\.mark\\.scenario\\(\\s*[\"']([^\"']+)[\"']"}
        (self.p.root / ".harness/config.json").write_text(json.dumps(cfg))
        self.p.write("docs/specs/chat.md", REQ_DOC)
        self.p.write("docs/domains/chat/test-scenarios.md", TS_DOC)
        self.p.write("tests/test_chat.py", TEST_PY)

    def tearDown(self):
        self.p.tmp.cleanup()

    def trace(self, *args):
        return self.p.harness("trace", *args, check=False)

    def test_clean(self):
        r = self.trace()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("요구사항 2개 · 시나리오 2개 중 2개가 테스트에 연결됨 (경고 0, 오류 0)", r.stdout)

    def test_show_chain(self):
        out = self.trace("CHAT-REQ-002").stdout
        self.assertIn("CHAT-TS-002", out)
        self.assertIn("tests/test_chat.py:9", out)
        self.assertIn("요구사항: CHAT-REQ-001", self.trace("CHAT-TS-001").stdout)

    def test_violations(self):
        self.p.write("tests/test_chat.py", TEST_PY.replace('"CHAT-TS-002"', '"CHAT-TS-001"')
                     + '\n\n@pytest.mark.scenario("CHAT-TS-999")\ndef test_ghost():\n    pass\n'
                     + '\n\n@pytest.mark.scenario("chat-1")\ndef test_bad():\n    pass\n')
        self.p.write("docs/domains/chat/test-scenarios.md", TS_DOC + "| CHAT-TS-001 | CHAT-REQ-002 | 중복 | api |\n| CHAT-TS-003 | CHAT-REQ-777 | 정의 없음 | api |\n")
        r = self.trace()
        self.assertNotEqual(r.returncode, 0)
        for msg in ["테스트 여러 개에 붙은 ID: CHAT-TS-001", "시나리오 문서에 없는 ID: CHAT-TS-999", "형식 오류: 'chat-1'",
                    "시나리오 ID 중복: CHAT-TS-001", "테스트가 없는 시나리오: CHAT-TS-002", "정의되지 않은 REQ: CHAT-REQ-777"]:
            self.assertIn(msg, r.stdout)

    def test_pending_doc_only_warns(self):
        self.p.write("docs/domains/chat/test-scenarios.md", TS_DOC.replace("> 상태: 구현됨", "> 상태: 구현 전")
                     + "| CHAT-TS-003 | CHAT-REQ-002 | 아직 테스트 없음 | api |\n")
        r = self.trace()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("경고: docs/domains/chat/test-scenarios.md", r.stdout)

    def test_requirement_coverage(self):
        self.p.write("docs/specs/chat.md", REQ_DOC + "#### CHAT-REQ-004 — 시나리오 없음\n")
        self.assertIn("시나리오가 없는 요구사항: CHAT-REQ-004", self.trace().stdout)
        self.assertEqual(self.trace().returncode, 0, "기본(warn)은 경고만")
        cfg = json.loads((self.p.root / ".harness/config.json").read_text())
        cfg["trace"]["requirement_coverage"] = "error"
        (self.p.root / ".harness/config.json").write_text(json.dumps(cfg))
        self.assertNotEqual(self.trace().returncode, 0)

    def test_default_marker_is_any_id_in_tests(self):
        cfg = json.loads((self.p.root / ".harness/config.json").read_text())
        cfg["trace"] = {"enabled": True, "scenario_docs": ["docs/domains/*/test-scenarios.md"]}
        (self.p.root / ".harness/config.json").write_text(json.dumps(cfg))
        self.p.write("test/chat_test.dart", "void main() {\n  test('CHAT-TS-001 지원하면 채팅방', () {});\n  test('CHAT-TS-002 제3자', () {});\n}\n")
        self.p.write("tests/test_chat.py", "")  # test_dirs(test/) 밖이라 기본 설정에서는 보지 않는다
        r = self.trace()
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_check_code_reports_trace_but_not_on_single_file(self):
        self.p.write("tests/test_chat.py", TEST_PY.replace('"CHAT-TS-002"', '"CHAT-TS-999"'))
        out = self.p.harness("check-code", check=False).stdout
        self.assertIn("[trace]", out)
        self.assertNotIn("[trace]", self.p.harness("check-code", "--file", "tests/test_chat.py", check=False).stdout)

    def test_disabled(self):
        cfg = json.loads((self.p.root / ".harness/config.json").read_text())
        cfg["trace"]["enabled"] = False
        (self.p.root / ".harness/config.json").write_text(json.dumps(cfg))
        self.p.write("tests/test_chat.py", TEST_PY.replace('"CHAT-TS-002"', '"CHAT-TS-999"'))
        self.assertIn("꺼짐", self.trace().stdout)
        self.assertNotIn("[trace]", self.p.harness("check-code", check=False).stdout)


AGENT_ENV = {**ENV, "HARNESS_AGENT": "1"}
PASS_REPORT = "판정: PASS\n등급: BLOCKER 0 · MAJOR 0 · MINOR 1 · 미검증(필수) 0\n검사: verify PASS · test PASS (1개)\n"


class WorkTest(unittest.TestCase):
    """작업 구간 — 자동 시작 · 라운드 · 완료 게이트(실행 기록 · 해시) · 자동 종료 · 안전한 정리 · settings 동기화"""

    def setUp(self):
        self.p = Project()
        self.p.harness("init", "flutter")
        self.p.write("pubspec.yaml", "name: my_app\n")
        self.p.write(".harness/checks.py", FAKE_RUNNER)
        self.set_cfg(risk_areas=["lib/features/pay/**"])
        self.assertEqual(self.p.commit("chore: 설치", verify=False).returncode, 0)
        self.p.run("git", "switch", "-q", "-c", "feat/chat")

    def tearDown(self):
        self.p.tmp.cleanup()

    def set_cfg(self, **kv):
        path = self.p.root / ".harness/config.json"
        cfg = json.loads(path.read_text())
        cfg.update(kv)
        path.write_text(json.dumps(cfg))

    def hook_write(self, rel):
        return self.p.decision({"tool_name": "Write", "session_id": "s1", "tool_input": {"file_path": str(self.p.root / rel)}})

    def spawn(self, role):
        return self.p.decision({"tool_name": "Agent", "session_id": "s1", "tool_input": {"subagent_type": role, "prompt": "x"}})

    def work(self, *args, env=AGENT_ENV):
        return subprocess.run([sys.executable, ".harness/core/scripts/work.py", *args], cwd=self.p.root, capture_output=True, text=True, env=env)

    def state(self):
        return json.loads((self.p.root / ".harness/_workspace/feat-chat/run.json").read_text())

    def run_cmd(self, *args):
        return subprocess.run([sys.executable, ".harness/core/scripts/harness.py", *args], cwd=self.p.root, capture_output=True, text=True, env=AGENT_ENV)

    def write_feature(self):
        self.p.write(CHAT, "void send() {}\n")
        self.p.write(CHAT_TEST, f"// EXPECT {CHAT} send\nimport 'package:my_app/features/chat/domain/chat.dart';\n")

    def test_auto_start_and_self_ignore(self):
        self.assertEqual(self.hook_write(CHAT), "allow")
        st = self.state()
        self.assertEqual(st["branch"], "feat/chat")
        self.assertEqual(st["sessions"], ["s1"])
        status = self.p.run("git", "status", "--porcelain").stdout
        self.assertNotIn("_workspace", status, "작업 공간은 프로젝트 .gitignore 없이도 git 에 안 보여야 한다")

    def test_review_rounds_capped(self):
        for n in (1, 2, 3):
            self.assertEqual(self.spawn("reviewer"), "allow")
            self.assertEqual(self.state()["rounds"][-1]["n"], n)
        self.assertEqual(self.spawn("reviewer"), "deny", "4번째 리뷰는 거부")
        self.assertIn("review_r3.md", self.work("current").stdout)

    def test_small_work_needs_verify_only(self):
        self.hook_write(CHAT)
        self.write_feature()
        r = self.work("gate")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("harness verify", r.stdout)
        self.run_cmd("verify")
        self.assertEqual(self.work("gate").returncode, 0, self.work("gate").stdout)

    def test_large_work_gate(self):
        self.spawn("planner")  # planner 를 쓰면 L
        self.write_feature()
        self.run_cmd("verify")
        out = self.work("gate").stdout
        self.assertIn("reviewer 검토가 없다", out)

        self.spawn("reviewer")
        report = self.p.root / self.state()["rounds"][-1]["path"]
        report.write_text(PASS_REPORT.replace("MAJOR 0", "MAJOR 2"))
        self.assertIn("PASS 조건이 아니다", self.work("gate").stdout)

        report.write_text(PASS_REPORT)
        self.assertIn("통과한 테스트 실행 기록이 없다", self.work("gate").stdout)
        self.run_cmd("test", CHAT_TEST)
        self.assertEqual(self.work("gate").returncode, 0, self.work("gate").stdout)

        # 리뷰 뒤 소스가 바뀌면 PASS 무효
        self.p.write(CHAT, "void send() {}\n// 바뀜\n")
        self.run_cmd("verify")
        self.run_cmd("test", CHAT_TEST)
        self.assertIn("리뷰(r1) 시작 뒤 소스가 바뀌었다", self.work("gate").stdout)

    def test_reviewer_new_test_does_not_invalidate_review(self):
        self.spawn("planner")
        self.write_feature()
        self.spawn("reviewer")
        self.p.write("test/features/chat/domain/chat_edge_test.dart", f"// EXPECT {CHAT} send\nimport 'package:my_app/features/chat/domain/chat.dart';\n")
        (self.p.root / self.state()["rounds"][-1]["path"]).write_text(PASS_REPORT)
        self.run_cmd("verify")
        self.run_cmd("test", "test/features/chat/domain/")
        self.assertEqual(self.work("gate").returncode, 0, self.work("gate").stdout)

    def test_risk_area_forces_large(self):
        self.hook_write(PAY)
        self.work("lane", "S")
        self.p.write(PAY, "int pay() => 1;\n")
        self.run_cmd("verify")
        out = self.work("gate").stdout
        self.assertIn("규모 L (위험 영역 변경: lib/features/pay/domain/pay.dart)", out)

    def test_commit_keeps_evidence_valid_and_push_finalizes(self):
        self.hook_write(CHAT)
        self.write_feature()
        self.run_cmd("verify")
        self.assertEqual(self.p.commit("feat: 채팅", verify=False).returncode, 0)
        r = self.work("pre-push", "origin", "x")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse((self.p.root / ".harness/_workspace/feat-chat").exists(), "통과하면 작업 공간을 정리한다")

    def test_human_push_is_not_gated(self):
        self.hook_write(CHAT)
        self.write_feature()
        self.assertEqual(self.work("pre-push", env=ENV).returncode, 0)
        self.assertTrue((self.p.root / ".harness/_workspace/feat-chat").exists(), "사람 push 는 정리도 하지 않는다")

    def test_git_pre_push_hook_blocks_agent(self):
        self.hook_write(CHAT)
        self.write_feature()
        self.p.commit("feat: 채팅", verify=False)
        bare = Path(self.p.tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        self.p.run("git", "remote", "add", "origin", str(bare))
        r = subprocess.run(["git", "push", "-q", "origin", "feat/chat"], cwd=self.p.root, capture_output=True, text=True, env=AGENT_ENV)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("작업 완료 조건 미충족", r.stdout + r.stderr)

    def test_stale_cleanup_is_safe(self):
        ws = self.p.root / ".harness/_workspace"
        old = time.time() - 40 * 86400

        def make(name, br, mtime_old=True):
            d = ws / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "run.json").write_text(json.dumps({"slug": name, "branch": br, "updated_ts": old, "rounds": []}))
            if mtime_old:
                for f in d.iterdir():
                    os.utime(f, (old, old))
            return d

        gone = make("feat-gone", "feat/gone")                # 브랜치 없음 + 30일 → 삭제
        self.p.run("git", "branch", "feat/open")
        self.p.write("x.txt", "x")
        self.p.run("git", "add", "x.txt")
        self.p.run("git", "commit", "-q", "--no-verify", "-m", "chore: x")
        self.p.run("git", "branch", "-f", "feat/open")       # main 에 없는 커밋 → 진행 중
        opened = make("feat-open", "feat/open")
        recent = make("feat-recent", "feat/gone2", mtime_old=False)  # 다른 세션이 최근에 씀
        self.hook_write(CHAT)                                 # 새 작업 시작 → 정리 실행
        self.assertFalse(gone.exists())
        self.assertTrue(opened.exists(), "머지 안 된 브랜치의 작업은 지우지 않는다")
        self.assertTrue(recent.exists(), "최근에 쓴 파일이 있으면 지우지 않는다")
        self.assertTrue((ws / "feat-chat").exists())

    def test_settings_sync_keeps_project_hooks(self):
        path = self.p.root / ".claude/settings.json"
        data = json.loads(path.read_text())
        data["hooks"]["PreToolUse"][0]["matcher"] = "Bash"          # 옛 하네스 훅
        data["hooks"].pop("SubagentStop")
        data["hooks"]["PreToolUse"].append({"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]})
        data["permissions"] = {"allow": ["Bash(ls)"]}
        path.write_text(json.dumps(data))
        self.assertIn("settings.json 의 하네스 훅", self.p.harness("check-rules", check=False).stdout)
        self.p.harness("sync")
        new = json.loads(path.read_text())
        self.assertIn("SubagentStop", new["hooks"])
        self.assertEqual(new["permissions"], {"allow": ["Bash(ls)"]})
        self.assertTrue(any(h["hooks"][0]["command"] == "echo mine" for h in new["hooks"]["PreToolUse"]))
        self.assertEqual(self.p.harness("check-rules", check=False).returncode, 0)



class GuardTest(unittest.TestCase):
    """Mutation Guard — 사후 검출(보장) · 사전 차단(최선 노력)"""

    def setUp(self):
        self.p = Project()
        self.p.harness("init", "flutter")
        self.p.write("pubspec.yaml", "name: my_app\n")
        self.p.write(CHAT, "void send() {}\n")
        self.p.write(CHAT_TEST, "// EXPECT x y\n")
        self.assertEqual(self.p.commit("chore: 설치", verify=False).returncode, 0)
        self.p.run("git", "switch", "-q", "-c", "feat/x")
        self.p.write("lib/dirty.dart", "int dirty = 1;\n")   # 호출 전부터 있던 사용자 변경 (baseline)

    def tearDown(self):
        self.p.tmp.cleanup()

    def hook(self, name, **payload):
        return self.p.hook(name, payload)

    def start(self, role, aid="agent1"):
        self.hook("subagent", hook_event_name="SubagentStart", agent_id=aid, agent_type=role, session_id="s1")

    def stop(self, aid="agent1"):
        self.hook("subagent", hook_event_name="SubagentStop", agent_id=aid, agent_type="x", session_id="s1")

    def returned(self):
        r = self.hook("post_edit", tool_name="Agent", tool_input={"subagent_type": "reviewer"})
        return json.loads(r.stdout)["reason"] if r.stdout.strip() else None

    def sub_tool(self, role, tool, **inp):
        out = self.hook("pre_tool", tool_name=tool, agent_id="agent1", agent_type=role, tool_input=inp).stdout.strip()
        return json.loads(out)["hookSpecificOutput"] if out else {"permissionDecision": "allow"}

    def test_planner_violation_detected_and_not_reverted(self):
        self.start("planner")
        self.p.write("lib/features/chat/domain/chat.dart", "void send() { /* planner */ }\n")   # 셸로 썼다고 가정
        self.stop()
        msg = self.returned()
        self.assertIn("사후 검출", msg)
        self.assertIn("lib/features/chat/domain/chat.dart", msg)
        self.assertNotIn("lib/dirty.dart", msg, "baseline 변경은 허용")
        self.assertIn("planner", (self.p.root / CHAT).read_text(), "되돌리지 않는다")
        self.assertIsNone(self.returned(), "한 번만 알린다")
        st = json.loads((self.p.root / ".harness/_workspace/feat-x/run.json").read_text())
        self.assertIn("planner_invalid", st)

    def test_planner_clean_run(self):
        self.start("planner")
        (self.p.root / ".harness/_workspace/feat-x/plan.md").write_text("# plan\n")
        self.stop()
        self.assertIsNone(self.returned())

    def test_reviewer_may_add_tests_but_not_touch_existing(self):
        self.start("reviewer")
        self.p.write("test/features/chat/domain/chat_edge_test.dart", "// new\n")
        self.stop()
        self.assertIsNone(self.returned(), "새 테스트 파일은 허용")

        self.start("reviewer", "agent2")
        self.p.write(CHAT_TEST, "// 약화\n")
        self.stop("agent2")
        self.assertIn("기존 테스트를 고치거나 지웠다", self.returned())

        self.start("reviewer", "agent3")
        (self.p.root / CHAT_TEST).unlink()
        self.stop("agent3")
        self.assertIn("기존 테스트를 고치거나 지웠다", self.returned())

    def test_commit_and_stage_detected(self):
        self.start("reviewer")
        self.p.run("git", "add", "lib/dirty.dart")
        self.stop()
        self.assertIn("stage(index)", self.returned())
        self.start("reviewer", "agent2")
        self.p.run("git", "commit", "-q", "--no-verify", "-m", "chore: x")
        self.stop("agent2")
        self.assertIn("HEAD 변경", self.returned())

    def test_main_agent_edits_during_background_review_are_excluded(self):
        self.start("reviewer")
        self.hook("pre_tool", tool_name="Edit", session_id="s1", tool_input={"file_path": str(self.p.root / CHAT)})  # 메인
        self.p.write(CHAT, "void send() { /* main */ }\n")
        self.stop()
        self.assertIsNone(self.returned())

    def test_realtime_block_is_labelled_best_effort(self):
        d = self.sub_tool("planner", "Write", file_path=str(self.p.root / CHAT))
        self.assertEqual(d["permissionDecision"], "deny")
        self.assertIn("사전 차단", d["permissionDecisionReason"])
        self.assertEqual(self.sub_tool("planner", "Write", file_path=str(self.p.root / ".harness/_workspace/feat-x/plan.md"))["permissionDecision"], "allow")
        self.assertEqual(self.sub_tool("reviewer", "Edit", file_path=str(self.p.root / CHAT_TEST))["permissionDecision"], "deny")
        self.assertEqual(self.sub_tool("reviewer", "Write", file_path=str(self.p.root / "test/new_test.dart"))["permissionDecision"], "allow")
        self.assertEqual(self.sub_tool("reviewer", "Bash", command="flutter test && git commit -am x")["permissionDecision"], "deny")
        self.assertEqual(self.sub_tool("reviewer", "Bash", command="git diff main && git status")["permissionDecision"], "allow")

    def test_violation_invalidates_review_round_in_gate(self):
        self.p.decision({"tool_name": "Agent", "session_id": "s1", "tool_input": {"subagent_type": "reviewer"}})
        self.start("reviewer")
        self.p.write(CHAT, "void send() { /* reviewer */ }\n")
        self.stop()
        out = subprocess.run([sys.executable, ".harness/core/scripts/work.py", "gate"], cwd=self.p.root, capture_output=True, text=True, env=ENV).stdout
        self.assertIn("Mutation Guard 위반으로 무효", out)

    def test_stop_hook_reports_background_violation(self):
        self.start("reviewer")
        self.p.write(CHAT, "void send() { /* bg */ }\n")
        self.stop()
        out = json.loads(self.hook("stop").stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("역할 위반", out["reason"])

    def test_disabled(self):
        cfg = json.loads((self.p.root / ".harness/config.json").read_text())
        cfg["guard"] = {"enabled": False}
        (self.p.root / ".harness/config.json").write_text(json.dumps(cfg))
        self.start("planner")
        self.p.write(CHAT, "void send() { /* off */ }\n")
        self.stop()
        self.assertIsNone(self.returned())
        self.assertEqual(self.sub_tool("planner", "Write", file_path=str(self.p.root / CHAT))["permissionDecision"], "allow")



def _iso(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


class UsageTest(unittest.TestCase):
    """토큰 실측 — 세션 기록 파싱 · 중복 제거 · 구간 · 역할 · Codex 증분 · 원문 미저장 · 도입 전후 버전"""

    def setUp(self):
        self.p = Project()
        self.p.harness("init", "flutter")
        self.p.commit("chore: 설치", verify=False)
        self.home = Path(self.p.tmp.name) / "home"
        self.env = {**ENV, "HARNESS_CLAUDE_HOME": str(self.home / ".claude"), "HARNESS_CODEX_HOME": str(self.home / ".codex")}
        self.pdir = self.home / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(self.p.root.resolve()))
        self.pdir.mkdir(parents=True)
        self.t0 = time.time() - 3600

    def tearDown(self):
        self.p.tmp.cleanup()

    def msg(self, mid, ts, branch="feat/chat", out=10, inp=100, read=1000):
        return json.dumps({"type": "assistant", "timestamp": _iso(ts), "gitBranch": branch, "message": {
            "id": mid, "content": [{"type": "text", "text": "SECRET 대화 원문"}],
            "usage": {"input_tokens": inp, "cache_creation_input_tokens": 50, "cache_read_input_tokens": read, "output_tokens": out}}})

    def write_claude(self):
        lines = [self.msg("m1", self.t0 + 10, out=5), self.msg("m1", self.t0 + 11, out=20),   # 같은 응답 두 줄 → 한 번
                 self.msg("m2", self.t0 + 20), self.msg("m0", self.t0 - 100)]                 # m0 은 구간 밖
        (self.pdir / "s1.jsonl").write_text("\n".join(lines) + "\n")
        sub = self.pdir / "s1/subagents"
        sub.mkdir(parents=True)
        (sub / "agent-a1.jsonl").write_text(self.msg("r1", self.t0 + 15, out=7) + "\n")
        (sub / "agent-a1.meta.json").write_text(json.dumps({"agentType": "reviewer"}))

    def usage_mod(self):
        code = (f"import sys,json; sys.path.insert(0, '.harness/core/scripts'); import usage; "
                f"st={{'slug':'feat-chat','branch':'feat/chat','started_ts':{self.t0},'sessions':['s1'],'rounds':[1],'harness_version':'0.4.0'}}; "
                f"print(json.dumps(usage.record_work(st, lane='L', end={self.t0 + 100})))")
        r = subprocess.run([sys.executable, "-c", code], cwd=self.p.root, capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_claude_window_roles_and_dedupe(self):
        self.write_claude()
        rec = self.usage_mod()
        main, rev = rec["roles"]["main"], rec["roles"]["reviewer"]
        self.assertEqual(main["messages"], 2, "m1 중복 제거 + m0 구간 밖")
        self.assertEqual(main["output"], 30, "m1 은 가장 큰 output(20) 하나 + m2(10)")
        self.assertEqual((rev["calls"], rev["output"]), (1, 7))
        self.assertEqual((rec["lane"], rec["harness_version"], rec["agent"]), ("L", "0.4.0", "claude"))
        raw = (self.p.root / ".harness/out/usage.jsonl").read_text()
        self.assertNotIn("SECRET", raw, "원문을 남기지 않는다")

    def test_codex_cumulative_delta(self):
        d = self.home / ".codex/sessions/2026/11/20"
        d.mkdir(parents=True)
        tc = lambda ts, i, c, o: json.dumps({"timestamp": _iso(ts), "type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": i, "cached_input_tokens": c, "output_tokens": o}}}})
        (d / "rollout-x.jsonl").write_text("\n".join([
            json.dumps({"type": "session_meta", "payload": {"id": "c1", "cwd": str(self.p.root), "git": {"branch": "feat/chat"}}}),
            tc(self.t0 - 50, 1000, 500, 10), tc(self.t0 + 30, 3000, 1500, 40), tc(self.t0 + 60, 5000, 2000, 90)]) + "\n")
        rec = self.usage_mod()
        cx = rec["roles"]["codex-main"]
        self.assertEqual((cx["output"], cx["cache_read"], cx["input"]), (80, 1500, 2500), "구간 끝 누적 − 구간 시작 전 누적")
        self.assertEqual(rec["agent"], "codex")

    def test_report_and_compare(self):
        self.write_claude()
        self.usage_mod()
        out = subprocess.run([sys.executable, ".harness/core/scripts/usage.py"], cwd=self.p.root, capture_output=True, text=True, env=self.env).stdout
        self.assertIn("| 0.4.0 | L | 1 |", out)
        self.assertIn("브랜치 실측", out)
        cmp_ = subprocess.run([sys.executable, ".harness/core/scripts/usage.py", "--compare", "0.3.0", "0.4.0"], cwd=self.p.root, capture_output=True, text=True, env=self.env).stdout
        self.assertIn("표본 부족", cmp_)

    def test_version_before_adoption(self):
        code = ("import sys; sys.path.insert(0, '.harness/core/scripts'); import usage, time; "
                "print(usage.harness_version_at(time.time()), '|', usage.harness_version_at(0))")
        out = subprocess.run([sys.executable, "-c", code], cwd=self.p.root, capture_output=True, text=True, env=self.env).stdout
        now, before = [x.strip() for x in out.split("|")]
        self.assertNotEqual(now, "도입 전")
        self.assertEqual(before, "도입 전", "하네스가 들어오기 전 시각은 '도입 전'")

    def test_finalize_records_usage(self):
        self.write_claude()
        self.p.run("git", "switch", "-q", "-c", "feat/chat")
        self.p.write("lib/a.dart", "int a = 1;\n")
        subprocess.run([sys.executable, ".harness/core/scripts/work.py", "lane", "S"], cwd=self.p.root, env=self.env, capture_output=True)
        subprocess.run([sys.executable, ".harness/core/scripts/harness.py", "verify"], cwd=self.p.root, env=self.env, capture_output=True)
        r = subprocess.run([sys.executable, ".harness/core/scripts/work.py", "end"], cwd=self.p.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = (self.p.root / ".harness/out/usage.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(rows[-1])["kind"], "work")



class DuplicateRuleTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.p.harness("init", "flutter")
        self.p.write("lib/a.dart", "int a = 1;\n")

    def tearDown(self):
        self.p.tmp.cleanup()

    def test_same_rule_in_two_documents(self):
        rule = "- 날짜는 항상 UTC 로 저장하고 화면에서만 지역 시간으로 바꾼다.\n"
        self.p.write(".harness/rules/data.md", '---\ndescription: 데이터\npaths:\n  - "lib/**"\n---\n# 데이터\n' + rule)
        self.p.harness("sync")
        self.assertEqual(self.p.harness("check-rules", check=False).returncode, 0)
        with open(self.p.root / "CLAUDE.md", "a") as f:
            f.write(rule)  # 어댑터에 복사
        out = self.p.harness("check-rules", check=False).stdout
        self.assertIn("같은 규칙이 여러 문서에 있다", out)
        self.assertIn("project/data.md", out)
        self.assertIn("CLAUDE.md", out)

    def test_fresh_project_has_no_false_positive(self):
        self.assertEqual(self.p.harness("check-rules", check=False).returncode, 0)


FAKE_GH = """#!/usr/bin/env python3
import json, sys, pathlib
cfg = json.loads(pathlib.Path("fakegh.json").read_text())
a = sys.argv[1:]
if a[:2] == ["pr", "list"]:
    print(json.dumps(cfg.get("prs", [])))
elif a[:2] == ["repo", "view"]:
    print(json.dumps({"nameWithOwner": "o/r"}))
elif a[:1] == ["api"]:
    print(json.dumps(cfg.get("runs", [])))
"""


class PromotionTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.p.harness("init", "flutter")
        cfg = json.loads((self.p.root / ".harness/config.json").read_text())
        cfg["promotion"] = [["dev", "main"]]
        (self.p.root / ".harness/config.json").write_text(json.dumps(cfg))
        self.p.write(".gitignore", (self.p.root / ".gitignore").read_text() + "fakegh.json\n")
        self.p.commit("chore: 설치", verify=False)
        bare = Path(self.p.tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        self.p.run("git", "remote", "add", "origin", str(bare))
        self.p.run("git", "push", "-q", "origin", "main", "main:dev")
        gh = Path(self.p.tmp.name) / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.env = {**ENV, "HARNESS_GH": str(gh)}
        self.fake(runs=[{"name": "Harness", "status": "completed", "conclusion": "success"}])

    def tearDown(self):
        self.p.tmp.cleanup()

    def fake(self, **kv):
        (self.p.root / "fakegh.json").write_text(json.dumps(kv))

    def check(self, head="dev", base="main"):
        return subprocess.run([sys.executable, ".harness/core/scripts/harness.py", "pr", "check-promotion", head, base],
                              cwd=self.p.root, capture_output=True, text=True, env=self.env)

    def advance_dev(self):
        self.p.run("git", "switch", "-q", "-c", "dev", "--track", "origin/dev")
        self.p.write("lib/x.dart", "int x = 1;\n")
        self.p.commit("feat: x", verify=False)
        self.p.run("git", "push", "-q", "origin", "dev")

    def test_empty_promotion(self):
        self.assertIn("빈 승격", self.check().stdout)

    def test_passes_and_rejects(self):
        self.advance_dev()
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("커밋 1개", r.stdout)
        self.fake(prs=[{"number": 7, "url": "https://x/pr/7"}], runs=[{"name": "Harness", "status": "completed", "conclusion": "success"}])
        self.assertIn("이미 열린 승격 PR", self.check().stdout)
        self.fake(runs=[{"name": "Flutter", "status": "completed", "conclusion": "failure"}, {"name": "Harness", "status": "in_progress", "conclusion": None}])
        out = self.check().stdout
        self.assertIn("검사 실패: Flutter", out)
        self.assertIn("아직 끝나지 않았다: Harness", out)
        self.assertIn("승격 경로가 아니다", self.check("main", "dev").stdout)

    def test_no_promotion_config(self):
        cfg = json.loads((self.p.root / ".harness/config.json").read_text())
        cfg.pop("promotion")
        (self.p.root / ".harness/config.json").write_text(json.dumps(cfg))
        self.assertIn("승격 경로(promotion)가 없다", self.check().stdout)



FAKE_GH_METRICS = """#!/usr/bin/env python3
import json, sys, pathlib
cfg = json.loads(pathlib.Path("fakegh.json").read_text())
a = sys.argv[1:]
if a[:2] == ["repo", "view"]:
    print(json.dumps({"nameWithOwner": "o/r"}))
elif a[:2] == ["api", "graphql"]:
    print(json.dumps({"data": {"repository": {"pullRequests": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": cfg["prs"]}}}}))
elif a[0] == "api" and "/jobs" in a[1]:
    print(json.dumps({"jobs": [{"name": "Lint", "conclusion": "failure"}, {"name": "Test", "conclusion": "success"}]}))
elif a[0] == "api" and "actions/runs" in a[1]:
    print(json.dumps({"workflow_runs": cfg["runs"]}))
"""


class MetricsGithubTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.p.write("README.md", "# app\n")
        self.p.run("git", "add", "README.md")  # .harness/core 없이
        self.p.run("git", "commit", "-q", "--no-verify", "-m", "chore: 하네스 전")
        self.before = _git(self.p.root, "rev-parse", "HEAD")
        self.p.harness("init", "flutter")
        self.p.write(".gitignore", (self.p.root / ".gitignore").read_text() + "fakegh.json\n")
        self.p.commit("chore: 하네스 설치", verify=False)
        self.after = _git(self.p.root, "rev-parse", "HEAD")
        gh = Path(self.p.tmp.name) / "gh"
        gh.write_text(FAKE_GH_METRICS)
        gh.chmod(0o755)
        self.env = {**ENV, "HARNESS_GH": str(gh)}
        pr = lambda n, title, head, oid: {"number": n, "title": title, "headRefName": head, "baseRefName": "main",
                                         "mergedAt": "2026-11-10T00:00:00Z", "mergeCommit": {"oid": oid}, "commits": {"totalCount": 2}}
        run = lambda i, name, br, concl, sha, t: {"id": i, "name": name, "event": "pull_request", "head_branch": br, "conclusion": concl,
                                                 "head_sha": sha, "created_at": f"2026-11-10T00:0{t}:00Z"}
        (self.p.root / "fakegh.json").write_text(json.dumps({
            "prs": [pr(1, "feat: a", "feat/a", self.before), pr(2, "fix: b", "fix/b", self.after), pr(3, "c", "feat/c", self.after),
                    pr(4, "staging", "main", self.after)],
            "runs": [run(10, "CI", "feat/a", "failure", self.before, 1), run(11, "CI", "feat/a", "success", self.before, 2),
                     run(12, "CI", "fix/b", "success", self.after, 3), run(13, "CI", "feat/c", "cancelled", self.after, 4)]}))

    def tearDown(self):
        self.p.tmp.cleanup()

    def test_metrics_by_version(self):
        r = subprocess.run([sys.executable, ".harness/core/scripts/harness.py", "metrics", "github"], cwd=self.p.root,
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("| 전체 | 3 |", out, "승격 PR(head=main) 제외")
        self.assertIn("| 도입 전 | 1 |", out)
        self.assertIn("버그 수정 비율", out)
        self.assertIn("CI / Lint 1", out)
        res = json.loads(sorted((self.p.root / ".harness/out/metrics").glob("github-*.json"))[-1].read_text())
        allpr = res["all"]["pr"]
        self.assertEqual(allpr["by_type"], {"feat": 2, "fix": 1}, "제목 접두사 → 없으면 브랜치 접두사")
        self.assertEqual(allpr["fix_ratio_pct"], 33.3)
        self.assertEqual(res["all"]["ci"]["first_pass_pct"], 50.0, "feat/a 첫 실행 실패 · fix/b 성공 · 취소 제외")
        self.assertEqual(res["by_version"]["도입 전"]["pr"]["prs"], 1)
        self.assertNotIn("fakegh", self.p.run("git", "status", "--porcelain").stdout)


if __name__ == "__main__":
    unittest.main()
