"""
하네스 템플릿 회귀 테스트 — 임시 프로젝트에 지금 작업 트리를 .harness/core 로 설치해 끝까지 돌려 본다.

실행: python3 -m unittest discover -s tests -v   (Flutter 없이 돈다 — 포맷 · 분석은 dart 가 없으면 건너뜀)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1]
ENV = {k: v for k, v in os.environ.items() if k not in {"HARNESS_SOURCE", "HARNESS_PROJECT_ROOT", "GITHUB_ACTIONS"}}
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


if __name__ == "__main__":
    unittest.main()
