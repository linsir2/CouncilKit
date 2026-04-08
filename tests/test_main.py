import json
from io import StringIO
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def complete_json(self, *, role: str, stage: str, prompt: str, context: str) -> dict[str, str]:
        self.calls.append((role, stage, prompt))
        if stage == "consensus":
            return {
                "title": "Minimal Support Backend",
                "summary": "A minimal consensus result.",
                "architecture": "FastAPI handles API, LangGraph handles flow, PostgreSQL handles persistence.",
                "mvp_scope": "Single chat endpoint with persisted conversation state.",
            }
        return {
            "message": f"{role} {stage} says: keep the design simple for {prompt}",
        }


class MainFlowTests(unittest.TestCase):
    def test_run_writes_minimal_artifacts(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            run_dir = main.run(
                prompt="Build a private-deployable AI support backend.",
                output_root=Path(temp_dir),
                client=FakeClient(),
            )

            self.assertTrue((run_dir / "transcript.md").exists())
            self.assertTrue((run_dir / "result.md").exists())
            self.assertTrue((run_dir / "run.json").exists())

            payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["prompt"], "Build a private-deployable AI support backend.")
            self.assertEqual(payload["agents"], ["FastAPI", "LangGraph", "PostgreSQL"])
            self.assertEqual(payload["stages"], ["alignment", "proposal", "challenge", "consensus"])
            self.assertEqual(payload["rounds_per_stage"], {"alignment": 3, "proposal": 3, "challenge": 3})
            self.assertEqual(payload["turn_count"], 28)
            transcript = (run_dir / "transcript.md").read_text(encoding="utf-8")
            self.assertIn("## alignment", transcript)
            self.assertIn("### round 1", transcript)
            self.assertIn("### round 2", transcript)
            self.assertIn("### round 3", transcript)
            self.assertIn("### FastAPI", transcript)
            self.assertIn("### LangGraph", transcript)
            self.assertIn("### PostgreSQL", transcript)

    def test_load_agent_packs_supports_aggregated_agent_json(self) -> None:
        import main

        packs = main.load_agent_packs(Path.cwd())
        fastapi = next(pack for pack in packs if pack.slug == "fastapi")

        self.assertEqual(fastapi.name, "FastAPI")
        self.assertIn("typed HTTP", fastapi.role)
        self.assertTrue(any("Pydantic" in item for item in fastapi.controversies))

    def test_fastapi_agent_json_keeps_auditable_judgment_fields(self) -> None:
        payload = json.loads(
            Path("examples/packs/fastapi/agent.json").read_text(encoding="utf-8")
        )

        self.assertEqual(payload["meta"]["schema_version"], "1.0")
        self.assertIn("derived_from", payload["meta"])
        self.assertTrue(payload["team_judgment"]["anchors"][0]["sources"])
        self.assertEqual(payload["team_judgment"]["anchors"][0]["confidence"], "high")
        self.assertIn("status", payload["team_judgment"]["controversies"][0])
        self.assertIn("mvp_usage", payload["debate_guide"])

    def test_all_agent_json_files_share_the_same_runtime_shape(self) -> None:
        pack_root = Path("examples/packs")
        for agent_json in sorted(pack_root.glob("*/agent.json")):
            payload = json.loads(agent_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["meta"]["schema_version"], "1.0")
            self.assertIn("derived_from", payload["meta"])
            self.assertIn("authority", payload["constitution"])
            self.assertTrue(payload["team_judgment"]["anchors"])
            self.assertTrue(payload["team_judgment"]["cases"])
            self.assertTrue(payload["team_judgment"]["controversies"])
            self.assertTrue(payload["team_judgment"]["anchors"][0]["sources"])
            self.assertIn("mvp_usage", payload["debate_guide"])

    def test_validate_agent_json_rejects_missing_section(self) -> None:
        import main

        broken = {
            "meta": {"id": "x", "name": "x", "schema_version": "1.0"},
            "identity": {"mission": "x"},
            "constitution": {"role": "x"},
            "team_judgment": {"anchors": [{"claim": "x"}], "cases": [{"claim": "x"}], "controversies": [{"question": "x"}]},
        }
        with self.assertRaises(ValueError):
            main.validate_agent_json(broken, Path("broken.json"))

    def test_load_agent_packs_fails_without_agent_json(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pack_dir = root / "examples" / "packs" / "ghost"
            pack_dir.mkdir(parents=True, exist_ok=True)
            with self.assertRaises(FileNotFoundError):
                main.load_agent_packs(root)

    def test_main_default_output_root_uses_project_runs(self) -> None:
        import main

        with (
            patch.object(sys, "argv", ["main.py", "--prompt", "p"]),
            patch("main.run") as mocked_run,
            patch("builtins.print"),
        ):
            mocked_run.return_value = Path("/tmp/fake-run")
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(mocked_run.call_args.kwargs["output_root"], None)
        self.assertEqual(mocked_run.call_args.kwargs["repo_root"], Path(main.__file__).resolve().parent)

    def test_main_relative_output_root_is_normalized_to_project(self) -> None:
        import main

        with (
            patch.object(sys, "argv", ["main.py", "--output-root", "runs-local", "--prompt", "p"]),
            patch("main.run") as mocked_run,
            patch("builtins.print"),
        ):
            mocked_run.return_value = Path("/tmp/fake-run")
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        expected = Path(main.__file__).resolve().parent / "runs-local"
        self.assertEqual(mocked_run.call_args.kwargs["output_root"], expected)

    def test_run_echo_prints_incremental_debate_logs(self) -> None:
        import main

        stream = StringIO()
        with TemporaryDirectory() as temp_dir:
            main.run(
                prompt="Build a private-deployable AI support backend.",
                output_root=Path(temp_dir),
                client=FakeClient(),
                echo=True,
                stream=stream,
            )

        output = stream.getvalue()
        self.assertIn("## alignment (round 1/3)", output)
        self.assertIn("## proposal (round 2/3)", output)
        self.assertIn("## challenge (round 3/3)", output)
        self.assertIn("## consensus", output)


if __name__ == "__main__":
    unittest.main()
