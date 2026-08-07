import unittest
from pathlib import Path


SANDBOX_DIR = Path(__file__).parent
DOCKERFILE = SANDBOX_DIR / "Dockerfile"
SYSTEM_PROMPT = SANDBOX_DIR / "SYSTEM_PROMPT.md"


class BrowserRuntimeTest(unittest.TestCase):
    def test_browser_dependencies_are_cross_architecture(self) -> None:
        dockerfile = DOCKERFILE.read_text()
        dependency_block = dockerfile.split(
            "# ── agent-browser system deps", 1
        )[1].split("\nUSER agent\n", 1)[0]

        self.assertNotIn('dpkg --print-architecture', dependency_block)
        self.assertIn("libatk-bridge2.0-0t64", dependency_block)
        self.assertIn("libgbm1", dependency_block)

    def test_image_uses_a_pinned_cross_arch_browser_and_launch_gate(self) -> None:
        dockerfile = DOCKERFILE.read_text()

        self.assertIn("ARG PLAYWRIGHT_VERSION=1.52.0", dockerfile)
        self.assertIn(
            'npx --yes "playwright@${PLAYWRIGHT_VERSION}" install chromium --no-shell',
            dockerfile,
        )
        self.assertIn(
            'AGENT_BROWSER_EXECUTABLE_PATH="/usr/local/bin/centaur-chromium"',
            dockerfile,
        )
        self.assertIn(
            'ln -s /usr/local/bin/centaur-chromium /usr/local/bin/chromium',
            dockerfile,
        )
        self.assertIn(
            'AGENT_BROWSER_ARGS="--no-sandbox,--disable-dev-shm-usage"',
            dockerfile,
        )
        self.assertIn("agent-browser open about:blank", dockerfile)
        self.assertIn("agent-browser close", dockerfile)
        self.assertNotIn(
            "apt-get install -y --no-install-recommends chromium-browser",
            dockerfile,
        )

    def test_prompt_exposes_the_sandbox_browser_workflow(self) -> None:
        prompt = SYSTEM_PROMPT.read_text()

        self.assertIn("Browser automation is available inside this sandbox", prompt)
        self.assertIn("agent-browser doctor --json", prompt)
        self.assertIn("a passing launch check is authoritative", prompt)
        self.assertIn("agent-browser skills get core --full", prompt)
        self.assertIn("Never use a user's local-machine browser", prompt)


if __name__ == "__main__":
    unittest.main()
