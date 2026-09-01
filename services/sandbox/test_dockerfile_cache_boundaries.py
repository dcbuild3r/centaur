import unittest
from pathlib import Path


DOCKERFILE = Path(__file__).with_name("Dockerfile")


class DockerfileCacheBoundaryTest(unittest.TestCase):
    def test_tool_changes_do_not_invalidate_harness_install(self) -> None:
        dockerfile = DOCKERFILE.read_text()

        harness_install = dockerfile.index("cargo +stable install --locked --path")
        tools_copy = dockerfile.index(
            "COPY --link --chown=1001:1001 tools/ /opt/centaur/tools/"
        )
        notion_contract_check = dockerfile.index(
            "RUN grep -Fq 'name = \"NOTION_API_KEY\", mode = \"replace\"'"
        )

        self.assertLess(harness_install, tools_copy)
        self.assertLess(tools_copy, notion_contract_check)


if __name__ == "__main__":
    unittest.main()
