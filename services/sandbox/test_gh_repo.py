from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SANDBOX_DIR = Path(__file__).parent
GH_REPO = SANDBOX_DIR / "gh-repo"


class GhRepoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.log = self.root / "calls.jsonl"
        gh = self.bin_dir / "gh"
        gh.write_text(
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            "payload=$(cat)\n"
            "jq -cn --arg token \"$GH_TOKEN\" --arg args \"$*\" --arg payload \"$payload\" "
            "'{token:$token,args:$args,payload:$payload}' >> \"$CALL_LOG\"\n"
            "if [[ \"${FAIL_POST:-}\" == 1 && \"$*\" == *'--method POST'* ]]; then\n"
            "  printf '%s\\n' 'HTTP 403: rate limit exceeded' >&2\n"
            "  exit 1\n"
            "fi\n"
            "if [[ \"${FAIL_PATCH:-}\" == 1 && \"$*\" == *'--method PATCH'* ]]; then\n"
            "  printf '%s\\n' 'HTTP 403: forbidden' >&2\n"
            "  exit 1\n"
            "fi\n"
            "if [[ \"$*\" == *'--method PATCH'* ]]; then\n"
            "  printf '%s' \"$payload\" > \"$STATE_FILE\"\n"
            "  printf '%s\\n' '{\"number\":42,\"html_url\":\"https://github.com/worldfnd/provekit/issues/42\"}'\n"
            "elif [[ \"$*\" == *'--method POST'* ]]; then\n"
            "  printf '%s\\n' '{\"number\":42,\"html_url\":\"https://github.com/worldfnd/provekit/issues/42\"}'\n"
            "elif [[ -s \"$STATE_FILE\" ]]; then\n"
            "  jq -c '. + {number:42,html_url:\"https://github.com/worldfnd/provekit/issues/42\"}' \"$STATE_FILE\"\n"
            "else\n"
            "  printf '%s\\n' '{\"number\":42,\"html_url\":\"https://github.com/worldfnd/provekit/issues/42\"}'\n"
            "fi\n"
        )
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _run(
        self,
        *args: str,
        input_text: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(GH_REPO), *args],
            input=input_text,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PATH": f"{self.bin_dir}:{os.environ['PATH']}",
                "CALL_LOG": str(self.log),
                "STATE_FILE": str(self.root / "state.json"),
                "GITHUB_TOKEN": "default-placeholder",
                "GITHUB_TOKEN_WORLDFND": "worldfnd-placeholder",
                **(extra_env or {}),
            },
        )

    def _calls(self) -> list[dict[str, str]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_issue_create_uses_rest_with_owner_token_and_verifies(self) -> None:
        body_file = self.root / "body.md"
        body_file.write_text("Reproduction details\n")

        result = self._run(
            "issue", "create", "--repo", "worldfnd/provekit", "--title", "Broken API",
            "--body-file", str(body_file), "--label", "bug,api", "-l", "triage",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "https://github.com/worldfnd/provekit/issues/42")
        calls = self._calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["token"], "worldfnd-placeholder")
        self.assertEqual(calls[0]["args"], "api --method POST repos/worldfnd/provekit/issues --input -")
        self.assertEqual(
            json.loads(calls[0]["payload"]),
            {"title": "Broken API", "body": "Reproduction details", "labels": ["bug", "api", "triage"]},
        )
        self.assertEqual(calls[1]["args"], "api repos/worldfnd/provekit/issues/42")

    def test_issue_create_supports_inline_values_and_default_token(self) -> None:
        result = self._run(
            "issue", "create", "--repo=acme/widget", "--title=Improve docs", "--body=Details",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self._calls()
        self.assertEqual(calls[0]["token"], "default-placeholder")
        self.assertEqual(json.loads(calls[0]["payload"])["body"], "Details")

    def test_issue_create_rejects_unsupported_arguments_without_calling_github(self) -> None:
        result = self._run(
            "issue", "create", "--repo", "worldfnd/provekit", "--title", "Test", "--assignee", "me",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("unsupported gh-repo issue create argument: --assignee", result.stderr)
        self.assertFalse(self.log.exists())

    def test_issue_create_preserves_github_error(self) -> None:
        result = self._run(
            "issue", "create", "-R", "worldfnd/provekit", "-t", "Test",
            extra_env={"FAIL_POST": "1"},
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("HTTP 403: rate limit exceeded", result.stderr)
        self.assertEqual(len(self._calls()), 1)

    def test_issue_edit_uses_rest_with_owner_token_and_verifies(self) -> None:
        body_file = self.root / "body.md"
        body_file.write_text("Updated details\n")

        result = self._run(
            "issue", "edit", "42", "--repo", "worldfnd/provekit",
            "--title", "Updated title", "--body-file", str(body_file),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "https://github.com/worldfnd/provekit/issues/42")
        calls = self._calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["token"], "worldfnd-placeholder")
        self.assertEqual(
            calls[0]["args"],
            "api --method PATCH repos/worldfnd/provekit/issues/42 --input -",
        )
        self.assertEqual(
            json.loads(calls[0]["payload"]),
            {"title": "Updated title", "body": "Updated details"},
        )
        self.assertEqual(calls[1]["args"], "api repos/worldfnd/provekit/issues/42")

    def test_issue_edit_supports_issue_url_and_inline_body(self) -> None:
        result = self._run(
            "issue", "edit", "https://github.com/worldfnd/provekit/issues/42",
            "--body=Updated details",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self._calls()
        self.assertEqual(calls[0]["token"], "worldfnd-placeholder")
        self.assertEqual(
            calls[0]["args"],
            "api --method PATCH repos/worldfnd/provekit/issues/42 --input -",
        )
        self.assertEqual(json.loads(calls[0]["payload"]), {"body": "Updated details"})

    def test_issue_edit_rejects_unsupported_arguments_without_calling_github(self) -> None:
        result = self._run(
            "issue", "edit", "42", "--repo", "worldfnd/provekit", "--add-assignee", "me",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("unsupported gh-repo issue edit argument: --add-assignee", result.stderr)
        self.assertFalse(self.log.exists())

    def test_issue_edit_can_clear_body(self) -> None:
        result = self._run(
            "issue", "edit", "42", "--repo", "worldfnd/provekit", "--body=",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self._calls()[0]["payload"]), {"body": ""})

    def test_issue_edit_requires_a_change_without_calling_github(self) -> None:
        result = self._run("issue", "edit", "42", "--repo", "worldfnd/provekit")

        self.assertEqual(result.returncode, 2)
        self.assertIn("at least one of --title, --body, or --body-file is required", result.stderr)
        self.assertFalse(self.log.exists())

    def test_issue_edit_preserves_github_error(self) -> None:
        result = self._run(
            "issue", "edit", "42", "--repo", "worldfnd/provekit", "--body", "Update",
            extra_env={"FAIL_PATCH": "1"},
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("HTTP 403: forbidden", result.stderr)
        self.assertEqual(len(self._calls()), 1)

    def test_non_issue_command_still_works_outside_a_checkout(self) -> None:
        result = self._run("api", "user")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._calls()[0]["token"], "default-placeholder")
        self.assertEqual(self._calls()[0]["args"], "api user")


if __name__ == "__main__":
    unittest.main()
