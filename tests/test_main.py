import os
import json
import subprocess
import sys
import unittest
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent
from unittest.mock import patch


def _write_skill(root: Path, slug: str, *, title: str, description: str) -> Path:
    skill_dir = root / "skills" / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        dedent(
            f"""\
            ---
            name: {slug}
            description: |
              {description}
            ---

            # {title}

            > {description}

            ## 角色定位

            {title} handles one narrow kind of judgment.

            ## 回答工作流（Agentic Protocol）

            1. Read the brief.
            2. Apply the skill's boundary.
            3. Return judgment, evidence, tradeoff, objection, needs verification, and confidence.
            """
        ),
        encoding="utf-8",
    )
    return skill_dir


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def complete_json(self, *, role: str, stage: str, prompt: str, context: str) -> dict[str, object]:
        self.calls.append((role, stage, prompt))
        skill_name = role.split("/")[0].strip()
        if stage == "synthesis":
            return {
                "title": "Skill Runtime Review",
                "summary": "The runtime keeps skill reasoning inspectable and reusable.",
                "decision": "Build the minimal single-file skill runtime first.",
                "key_decisions": [
                    "Treat SKILL.md as the only semantic source.",
                    "Persist replayable traces from day one.",
                ],
                "strongest_objections": [
                    {
                        "skill": "FastAPI",
                        "objection": "Do not let transport concerns leak into orchestration.",
                        "severity": "medium",
                    }
                ],
                "next_steps": [
                    "Implement SkillSpec and SkillInstance loading.",
                    "Define the six-slot turn result contract.",
                ],
                "open_questions": [
                    "How much context should a single skill see per turn?"
                ],
                "skill_notes": [
                    {"skill": "FastAPI", "note": "Keep contracts explicit."},
                    {"skill": "Do Things That Don't Scale", "note": "Use raw traces before over-architecting."},
                ],
            }
        return {
            "message": f"{skill_name} keeps the runtime inside its real boundary.",
            "judgment": f"{skill_name} gives one direct judgment.",
            "evidence": [f"{skill_name} evidence from SKILL.md"],
            "tradeoff": f"{skill_name} names the main tradeoff.",
            "objection": f"{skill_name} objects to overbuilding the first version.",
            "needs_verification": [f"{skill_name} needs one real-world replay."],
            "confidence": "high",
        }


class MainFlowTests(unittest.TestCase):
    def test_run_writes_single_file_skill_runtime_artifacts(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Demo\n\nRuntime project snapshot.", encoding="utf-8")
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            _write_skill(
                root,
                "do-things-that-dont-scale",
                title="Do Things That Don't Scale",
                description="Early growth method skill.",
            )

            run_dir = main.run(
                prompt="Design the first skill runtime harness.",
                output_root=root / "traces" / "raw",
                client=FakeClient(),
                repo_root=root,
                project_root=root,
                skill_root=root / "skills",
                skills=["fastapi", "do-things-that-dont-scale"],
            )

            self.assertTrue((run_dir / "transcript.md").exists())
            self.assertTrue((run_dir / "result.md").exists())
            self.assertTrue((run_dir / "debate.md").exists())
            self.assertTrue((run_dir / "run.json").exists())

            payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["task"]["prompt"], "Design the first skill runtime harness.")
            self.assertEqual(payload["task"]["mode"], "review")
            self.assertEqual(payload["turn_count"], 5)
            self.assertEqual({item["name"] for item in payload["skills"]}, {"FastAPI", "Do Things That Don't Scale"})
            self.assertEqual(payload["admission"]["status"], "accept")
            self.assertEqual(set(payload["admission"]["selected_skills"]), {"fastapi", "do-things-that-dont-scale"})
            self.assertEqual(payload["harness"]["source_of_truth"], "SKILL.md")
            self.assertEqual(payload["harness"]["admission_status"], "accept")
            self.assertEqual(
                payload["harness"]["reduction_slots"],
                ["judgment", "evidence", "tradeoff", "objection", "needs_verification", "confidence"],
            )
            self.assertEqual(len(payload["turns"]), 4)
            self.assertEqual(payload["source_kind"], "raw")

            transcript = (run_dir / "transcript.md").read_text(encoding="utf-8")
            self.assertIn("## survey", transcript)
            self.assertIn("## review", transcript)
            self.assertIn("- judgment:", transcript)
            self.assertIn("- tradeoff:", transcript)

            result = (run_dir / "result.md").read_text(encoding="utf-8")
            self.assertIn("## Key Decisions", result)
            self.assertIn("## Strongest Objections", result)
            self.assertIn("## Skill Notes", result)

            debate = (run_dir / "debate.md").read_text(encoding="utf-8")
            self.assertIn("## Participants & Provenance", debate)
            self.assertIn("## Debate Map", debate)
            self.assertIn("## Synthesis Delta", debate)
            self.assertIn("## Harness Handoff", debate)
            self.assertIn("- matched_terms:", debate)

    def test_run_records_runtime_payload_failure_instead_of_crashing(self) -> None:
        import main

        class BrokenTurnClient:
            def complete_json(self, *, role: str, stage: str, prompt: str, context: str) -> dict[str, object]:
                del role, stage, prompt, context
                return {
                    "judgment": "missing message slot",
                    "evidence": ["x"],
                    "tradeoff": "x",
                    "objection": "x",
                    "needs_verification": ["x"],
                    "confidence": "high",
                }

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Demo\n\nRuntime project snapshot.", encoding="utf-8")
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")

            run_dir = main.run(
                prompt="Design the first skill runtime harness.",
                output_root=root / "traces" / "raw",
                client=BrokenTurnClient(),
                repo_root=root,
                project_root=root,
                skill_root=root / "skills",
                skills=["fastapi"],
            )

            payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["synthesis"]["title"], "Session halted by runtime payload gate")
            events_path = run_dir / "failure-events.jsonl"
            self.assertTrue(events_path.exists())
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["failure_code"], "slot_missing_required")
            self.assertEqual(events[0]["source_stage"], "dispatch")

    def test_run_records_synthesis_payload_failure_instead_of_crashing(self) -> None:
        import main

        class BrokenSynthesisClient:
            def complete_json(self, *, role: str, stage: str, prompt: str, context: str) -> dict[str, object]:
                del prompt, context
                if stage == "synthesis":
                    return {
                        "summary": "missing required synthesis title",
                        "decision": "x",
                        "key_decisions": ["x"],
                        "strongest_objections": [{"skill": "FastAPI", "objection": "x", "severity": "medium"}],
                        "next_steps": ["x"],
                        "open_questions": [],
                        "skill_notes": [{"skill": "FastAPI", "note": "x"}],
                    }
                skill_name = role.split("/")[0].strip()
                return {
                    "message": f"{skill_name} keeps the runtime inside its real boundary.",
                    "judgment": f"{skill_name} gives one direct judgment.",
                    "evidence": [f"{skill_name} evidence from SKILL.md"],
                    "tradeoff": f"{skill_name} names the main tradeoff.",
                    "objection": f"{skill_name} objects to overbuilding the first version.",
                    "needs_verification": [f"{skill_name} needs one real-world replay."],
                    "confidence": "high",
                }

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Demo\n\nRuntime project snapshot.", encoding="utf-8")
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")

            run_dir = main.run(
                prompt="Design the first skill runtime harness.",
                output_root=root / "traces" / "raw",
                client=BrokenSynthesisClient(),
                repo_root=root,
                project_root=root,
                skill_root=root / "skills",
                skills=["fastapi"],
            )

            payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["synthesis"]["title"], "Session halted by runtime payload gate")
            events_path = run_dir / "failure-events.jsonl"
            self.assertTrue(events_path.exists())
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["failure_code"], "synthesis_payload_invalid")
            self.assertEqual(events[0]["source_stage"], "synthesis")

    def test_load_skill_specs_supports_single_file_skills_and_ignores_legacy_sidecars(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_dir = _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            (skill_dir / "constitution.yaml").write_text("{}", encoding="utf-8")
            (skill_dir / "sources.jsonl").write_text("", encoding="utf-8")
            skills = main.load_skill_specs(root, root / "skills")
            fastapi = next(skill for skill in skills if skill.slug == "fastapi")

            self.assertEqual(fastapi.name, "FastAPI")
            self.assertIn("Typed API boundary owner", fastapi.description)

    def test_load_skill_specs_fails_without_skill_markdown(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_dir = root / "skills" / "ghost"
            skill_dir.mkdir(parents=True, exist_ok=True)
            with self.assertRaises(FileNotFoundError):
                main.load_skill_specs(root, root / "skills")

    def test_project_snapshot_uses_live_working_tree_not_deleted_index_entries(self) -> None:
        from src.councilkit.loader import project_snapshot

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
            (root / "README.md").write_text("# Demo\n\nSnapshot test.", encoding="utf-8")
            ghost = root / "ghost.txt"
            ghost.write_text("ghost", encoding="utf-8")
            subprocess.run(["git", "add", "README.md", "ghost.txt"], cwd=root, check=True, capture_output=True, text=True)
            ghost.unlink()

            runtime_file = root / "src" / "councilkit" / "runtime.py"
            runtime_file.parent.mkdir(parents=True, exist_ok=True)
            runtime_file.write_text("print('runtime')\n", encoding="utf-8")
            skill_file = root / "skills" / "langgraph" / "SKILL.md"
            skill_file.parent.mkdir(parents=True, exist_ok=True)
            skill_file.write_text("# LangGraph\n", encoding="utf-8")

            snapshot = project_snapshot(root)

            self.assertIn("Top project files:", snapshot)
            self.assertNotIn("ghost.txt", snapshot)
            self.assertIn("src/councilkit/runtime.py", snapshot)
            self.assertIn("skills/langgraph/SKILL.md", snapshot)

    def test_main_default_output_root_uses_project_runs(self) -> None:
        import main
        from src.councilkit import cli

        with (
            patch.object(sys, "argv", ["main.py", "--prompt", "p"]),
            patch.object(cli, "run") as mocked_run,
            patch("builtins.print"),
        ):
            mocked_run.return_value = Path("/tmp/fake-run")
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        expected = Path(main.__file__).resolve().parent / "traces" / "raw"
        self.assertEqual(mocked_run.call_args.kwargs["output_root"], expected)
        self.assertEqual(mocked_run.call_args.kwargs["repo_root"], Path(main.__file__).resolve().parent)

    def test_main_emit_harness_contract_skips_runtime(self) -> None:
        import main
        from src.councilkit import cli

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-harness-contract",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--project-root",
                        str(root),
                    ],
                ),
                patch.object(cli, "run") as mocked_run,
                patch("builtins.print") as mocked_print,
            ):
                exit_code = main.main()

            self.assertEqual(exit_code, 0)
            mocked_run.assert_not_called()
            payload = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(payload["admission"]["status"], "accept")
            self.assertEqual(payload["harness"]["source_of_truth"], "SKILL.md")
            self.assertEqual(payload["harness"]["selected_skill_slugs"], ["fastapi"])
            self.assertEqual(payload["harness"]["loaded_skill_slugs"], ["fastapi"])

    def test_main_emit_harness_contract_writes_output_file(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_file = root / "artifacts" / "harness-contract.json"
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-harness-contract",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--contract-output",
                        str(out_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                exit_code = main.main()

            self.assertEqual(exit_code, 0)
            self.assertTrue(out_file.exists())
            payload = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["admission"]["status"], "accept")
            self.assertEqual(payload["harness"]["mode"], "review")
            self.assertEqual(payload["harness"]["selected_skill_slugs"], ["fastapi"])

    def test_main_verify_harness_contract_passes_for_fresh_payload(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract_file = root / "harness-contract.json"
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-harness-contract",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--contract-output",
                        str(contract_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                emit_exit = main.main()
            self.assertEqual(emit_exit, 0)

            with (
                patch.object(
                    sys,
                    "argv",
                    ["main.py", "--verify-harness-contract", str(contract_file)],
                ),
                patch("builtins.print") as mocked_print,
            ):
                verify_exit = main.main()
            self.assertEqual(verify_exit, 0)
            report = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["checked_skills"], ["fastapi"])

    def test_main_verify_harness_contract_detects_hash_mismatch(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract_file = root / "harness-contract.json"
            skill_dir = _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-harness-contract",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--contract-output",
                        str(contract_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                emit_exit = main.main()
            self.assertEqual(emit_exit, 0)

            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text(skill_file.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    ["main.py", "--verify-harness-contract", str(contract_file)],
                ),
                patch("builtins.print") as mocked_print,
            ):
                verify_exit = main.main()
            self.assertEqual(verify_exit, 2)
            report = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(report["status"], "fail")
            self.assertTrue(any(item["code"] == "prompt_hash_mismatch" for item in report["issues"]))

    def test_main_verify_harness_contract_resolves_relative_skill_file_without_cwd_dependency(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_dir = _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            contract_file = root / "harness-contract.json"
            digest = sha256((skill_dir / "SKILL.md").read_text(encoding="utf-8").strip().encode("utf-8")).hexdigest()
            contract_payload = {
                "version": "v1",
                "source_of_truth": "SKILL.md",
                "prompt_contract": "SKILL.md acts as prompt, persona, and reasoning contract.",
                "reduction_slots": [
                    "judgment",
                    "evidence",
                    "tradeoff",
                    "objection",
                    "needs_verification",
                    "confidence",
                ],
                "mode": "review",
                "stage_order": ["survey", "review", "synthesis"],
                "rounds_per_stage": {"survey": 1, "review": 1},
                "selected_skill_slugs": ["fastapi"],
                "loaded_skill_slugs": ["fastapi"],
                "skills": [
                    {
                        "slug": "fastapi",
                        "name": "FastAPI",
                        "skill_file": "skills/fastapi/SKILL.md",
                        "skill_mtime": None,
                        "prompt_sha256": digest,
                    }
                ],
                "admission_status": "accept",
            }
            contract_file.write_text(json.dumps(contract_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            original_cwd = Path.cwd()
            try:
                os.chdir("/tmp")
                with (
                    patch.object(
                        sys,
                        "argv",
                        ["main.py", "--verify-harness-contract", str(contract_file)],
                    ),
                    patch("builtins.print") as mocked_print,
                ):
                    verify_exit = main.main()
            finally:
                os.chdir(original_cwd)

            self.assertEqual(verify_exit, 0)
            report = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["checked_skills"], ["fastapi"])

    def test_main_emit_session_spec_from_contract_pipeline(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract_file = root / "harness-contract.json"
            session_spec_file = root / "session-spec.json"
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-harness-contract",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--contract-output",
                        str(contract_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                emit_exit = main.main()
            self.assertEqual(emit_exit, 0)

            with (
                patch.object(
                    sys,
                    "argv",
                    ["main.py", "--verify-harness-contract", str(contract_file)],
                ),
                patch("builtins.print"),
            ):
                verify_exit = main.main()
            self.assertEqual(verify_exit, 0)

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-session-spec",
                        "--session-spec-from",
                        str(contract_file),
                        "--session-spec-output",
                        str(session_spec_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                session_exit = main.main()
            self.assertEqual(session_exit, 0)
            self.assertTrue(session_spec_file.exists())
            payload = json.loads(session_spec_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], "v1")
            self.assertEqual(payload["mode"], "review")
            self.assertEqual(payload["source_of_truth"], "SKILL.md")
            self.assertEqual(payload["participants"][0]["slug"], "fastapi")
            self.assertEqual(payload["selected_skill_slugs"], ["fastapi"])
            self.assertEqual(payload["admission"]["status"], "accept")
            self.assertEqual(
                [item["stage"] for item in payload["stages"]],
                ["survey", "review", "synthesis"],
            )
            self.assertEqual(
                payload["turn_schedule"],
                [
                    {
                        "turn_index": 1,
                        "stage": "survey",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "skill_name": "FastAPI",
                    },
                    {
                        "turn_index": 2,
                        "stage": "review",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "skill_name": "FastAPI",
                    },
                ],
            )

    def test_main_emit_session_spec_from_selection_skips_runtime(self) -> None:
        import main
        from src.councilkit import cli

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-session-spec",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                    ],
                ),
                patch.object(cli, "run") as mocked_run,
                patch("builtins.print") as mocked_print,
            ):
                exit_code = main.main()

            self.assertEqual(exit_code, 0)
            mocked_run.assert_not_called()
            payload = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(payload["mode"], "review")
            self.assertEqual(payload["participants"][0]["slug"], "fastapi")
            self.assertEqual(payload["admission"]["status"], "accept")
            self.assertEqual(len(payload["turn_schedule"]), 2)
            self.assertEqual(payload["turn_schedule"][0]["skill_slug"], "fastapi")

    def test_main_emit_dispatch_template_from_selection_skips_runtime(self) -> None:
        import main
        from src.councilkit import cli

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-dispatch-template",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--project-root",
                        str(root),
                    ],
                ),
                patch.object(cli, "run") as mocked_run,
                patch("builtins.print") as mocked_print,
            ):
                exit_code = main.main()

            self.assertEqual(exit_code, 0)
            mocked_run.assert_not_called()
            payload = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(payload["template_version"], "v1")
            self.assertEqual(payload["prompt"], "Review API contracts.")
            self.assertEqual(payload["session_spec"]["selected_skill_slugs"], ["fastapi"])
            self.assertEqual(len(payload["turns"]), 2)
            self.assertEqual(payload["turns"][0]["stage"], "survey")
            self.assertEqual(payload["turns"][0]["skill_slug"], "fastapi")
            self.assertEqual(payload["turns"][0]["message"], "")
            self.assertEqual(payload["turns"][0]["evidence"], [])
            self.assertEqual(payload["turns"][0]["confidence"], "")
            self.assertEqual(payload["synthesis"]["title"], "")

    def test_main_emit_dispatch_template_from_run_trace_keeps_task_context(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Demo\n\nRuntime project snapshot.", encoding="utf-8")
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            run_dir = main.run(
                prompt="Design the first skill runtime harness.",
                output_root=root / "traces" / "raw",
                client=FakeClient(),
                repo_root=root,
                project_root=root,
                skill_root=root / "skills",
                skills=["fastapi"],
            )

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-dispatch-template",
                        "--dispatch-template-from",
                        str(run_dir / "run.json"),
                    ],
                ),
                patch("builtins.print") as mocked_print,
            ):
                exit_code = main.main()

            self.assertEqual(exit_code, 0)
            payload = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(payload["prompt"], "Design the first skill runtime harness.")
            self.assertEqual(payload["project_root"], str(root))
            self.assertEqual(payload["session_spec"]["selected_skill_slugs"], ["fastapi"])
            self.assertEqual(len(payload["turns"]), 2)
            self.assertEqual(payload["turns"][1]["stage"], "review")
            self.assertEqual(payload["session_spec"]["turn_schedule"][1]["stage"], "review")

    def test_main_validate_dispatch_payload_passes_without_writing_artifacts(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            session_spec_file = root / "session-spec.json"
            payload_file = root / "dispatch-payload.json"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-session-spec",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--session-spec-output",
                        str(session_spec_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(main.main(), 0)

            session_spec = json.loads(session_spec_file.read_text(encoding="utf-8"))
            payload = {
                "prompt": "Imported harness run brief.",
                "project_root": str(root),
                "shared_brief": "Imported from harness.",
                "session_spec": session_spec,
                "turns": [
                    {
                        "stage": "survey",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "message": "Survey message",
                        "judgment": "Survey judgment.",
                        "evidence": ["Survey evidence"],
                        "tradeoff": "Survey tradeoff.",
                        "objection": "Survey objection.",
                        "needs_verification": ["Survey verify"],
                        "confidence": "high",
                    },
                    {
                        "stage": "review",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "message": "Review message",
                        "judgment": "Review judgment.",
                        "evidence": ["Review evidence"],
                        "tradeoff": "Review tradeoff.",
                        "objection": "Review objection.",
                        "needs_verification": ["Review verify"],
                        "confidence": "medium",
                    },
                ],
                "synthesis": {
                    "title": "Imported synthesis",
                    "summary": "Imported run stays schema compatible.",
                    "decision": "Accept imported turns and preserve trace shape.",
                    "key_decisions": ["Keep six-slot contract stable."],
                    "strongest_objections": [
                        {"skill": "FastAPI", "objection": "Do not blur boundaries.", "severity": "medium"}
                    ],
                    "next_steps": ["Add ingestion for external harness outputs."],
                    "open_questions": ["Should strict hash check be default?"],
                    "skill_notes": [{"skill": "FastAPI", "note": "Keep contract explicit."}],
                },
            }
            payload_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    ["main.py", "--validate-dispatch-payload", str(payload_file)],
                ),
                patch("builtins.print") as mocked_print,
            ):
                exit_code = main.main()

            self.assertEqual(exit_code, 0)
            report = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["issues_by_turn"], [])
            self.assertEqual(report["issues_by_section"], [])
            self.assertEqual(report["recommended_repair_order"], [])
            self.assertEqual(report["repair_hints"], [])
            self.assertEqual(
                report["expected_contract"]["reduction_slots"],
                ["judgment", "evidence", "tradeoff", "objection", "needs_verification", "confidence"],
            )
            self.assertEqual(report["checked_skills"], ["fastapi"])
            self.assertEqual(report["selected_skill_slugs"], ["fastapi"])
            self.assertEqual(report["turn_count"], 2)
            self.assertFalse((root / "traces").exists())

    def test_main_validate_dispatch_payload_hash_mismatch_can_warn(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_dir = _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            session_spec_file = root / "session-spec.json"
            payload_file = root / "dispatch-payload.json"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-session-spec",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--session-spec-output",
                        str(session_spec_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(main.main(), 0)

            session_spec = json.loads(session_spec_file.read_text(encoding="utf-8"))
            payload = {
                "prompt": "Imported harness run brief.",
                "project_root": str(root),
                "session_spec": session_spec,
                "turns": [
                    {
                        "stage": "survey",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "judgment": "Survey judgment.",
                        "evidence": ["Survey evidence"],
                        "tradeoff": "Survey tradeoff.",
                        "objection": "Survey objection.",
                        "needs_verification": ["Survey verify"],
                        "confidence": "high",
                    },
                    {
                        "stage": "review",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "judgment": "Review judgment.",
                        "evidence": ["Review evidence"],
                        "tradeoff": "Review tradeoff.",
                        "objection": "Review objection.",
                        "needs_verification": ["Review verify"],
                        "confidence": "medium",
                    },
                ],
                "synthesis": {
                    "title": "Imported synthesis",
                    "summary": "Imported run stays schema compatible.",
                    "decision": "Accept imported turns and preserve trace shape.",
                    "key_decisions": ["Keep six-slot contract stable."],
                    "strongest_objections": [
                        {"skill": "FastAPI", "objection": "Do not blur boundaries.", "severity": "medium"}
                    ],
                    "next_steps": ["Add ingestion for external harness outputs."],
                    "open_questions": ["Should strict hash check be default?"],
                    "skill_notes": [{"skill": "FastAPI", "note": "Keep contract explicit."}],
                },
            }
            payload_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text(skill_file.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    ["main.py", "--validate-dispatch-payload", str(payload_file)],
                ),
                patch("builtins.print") as mocked_print_fail,
            ):
                fail_exit = main.main()

            self.assertEqual(fail_exit, 2)
            fail_report = json.loads(mocked_print_fail.call_args_list[-1].args[0])
            self.assertEqual(fail_report["status"], "fail")
            self.assertEqual(fail_report["issues"][0]["code"], "prompt_hash_mismatch")
            self.assertEqual(fail_report["repair_hints"][0]["code"], "prompt_hash_mismatch")
            self.assertEqual(
                fail_report["repair_hints"][0]["action"],
                "regenerate_session_artifacts",
            )
            self.assertEqual(fail_report["issues_by_section"][0]["section"], "session_spec")
            self.assertTrue(fail_report["issues_by_section"][0]["blocking"])
            self.assertEqual(fail_report["recommended_repair_order"][0]["scope_type"], "section")
            self.assertEqual(fail_report["recommended_repair_order"][0]["scope_id"], "session_spec")
            self.assertEqual(fail_report["recommended_repair_order"][0]["primary_action"], "regenerate_session_artifacts")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--validate-dispatch-payload",
                        str(payload_file),
                        "--ignore-hash-mismatch",
                    ],
                ),
                patch("builtins.print") as mocked_print_warn,
            ):
                warn_exit = main.main()

            self.assertEqual(warn_exit, 0)
            warn_report = json.loads(mocked_print_warn.call_args_list[-1].args[0])
            self.assertEqual(warn_report["status"], "pass_with_warning")
            self.assertTrue(any(item["code"] == "prompt_hash_mismatch" for item in warn_report["issues"]))
            self.assertTrue(any(item["code"] == "prompt_hash_mismatch" for item in warn_report["repair_hints"]))
            self.assertEqual(warn_report["issues_by_section"][0]["section"], "session_spec")
            self.assertFalse(warn_report["issues_by_section"][0]["blocking"])
            self.assertGreaterEqual(warn_report["issues_by_section"][0]["priority_rank"], 1000)
            self.assertEqual(warn_report["recommended_repair_order"][0]["scope_type"], "section")
            self.assertEqual(warn_report["recommended_repair_order"][0]["scope_id"], "session_spec")
            self.assertEqual(warn_report["recommended_repair_order"][0]["primary_action"], "regenerate_session_artifacts")

    def test_main_validate_dispatch_payload_accepts_run_trace_source(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Demo\n\nRuntime project snapshot.", encoding="utf-8")
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            run_dir = main.run(
                prompt="Design the first skill runtime harness.",
                output_root=root / "traces" / "raw",
                client=FakeClient(),
                repo_root=root,
                project_root=root,
                skill_root=root / "skills",
                skills=["fastapi"],
            )

            with (
                patch.object(
                    sys,
                    "argv",
                    ["main.py", "--validate-dispatch-payload", str(run_dir / "run.json")],
                ),
                patch("builtins.print") as mocked_print,
            ):
                exit_code = main.main()

            self.assertEqual(exit_code, 0)
            report = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["checked_skills"], ["fastapi"])
            self.assertEqual(report["selected_skill_slugs"], ["fastapi"])
            self.assertEqual(report["turn_count"], 2)

    def test_main_validate_dispatch_payload_localizes_turn_confidence_error(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            session_spec_file = root / "session-spec.json"
            payload_file = root / "dispatch-invalid-confidence.json"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-session-spec",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--session-spec-output",
                        str(session_spec_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(main.main(), 0)

            session_spec = json.loads(session_spec_file.read_text(encoding="utf-8"))
            payload = {
                "prompt": "Imported harness run brief.",
                "project_root": str(root),
                "session_spec": session_spec,
                "turns": [
                    {
                        "stage": "survey",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "judgment": "Survey judgment.",
                        "evidence": ["Survey evidence"],
                        "tradeoff": "Survey tradeoff.",
                        "objection": "Survey objection.",
                        "needs_verification": ["Survey verify"],
                        "confidence": "extreme",
                    },
                    {
                        "stage": "review",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "judgment": "Review judgment.",
                        "evidence": ["Review evidence"],
                        "tradeoff": "Review tradeoff.",
                        "objection": "Review objection.",
                        "needs_verification": ["Review verify"],
                        "confidence": "medium",
                    },
                ],
                "synthesis": {
                    "title": "Imported synthesis",
                    "summary": "Imported run stays schema compatible.",
                    "decision": "Accept imported turns and preserve trace shape.",
                    "key_decisions": ["Keep six-slot contract stable."],
                    "strongest_objections": [
                        {"skill": "FastAPI", "objection": "Do not blur boundaries.", "severity": "medium"}
                    ],
                    "next_steps": ["Add ingestion for external harness outputs."],
                    "open_questions": ["Should strict hash check be default?"],
                    "skill_notes": [{"skill": "FastAPI", "note": "Keep contract explicit."}],
                },
            }
            payload_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    ["main.py", "--validate-dispatch-payload", str(payload_file)],
                ),
                patch("builtins.print") as mocked_print,
            ):
                exit_code = main.main()

            self.assertEqual(exit_code, 2)
            report = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(report["status"], "fail")
            issue = report["issues"][0]
            self.assertEqual(issue["code"], "slot_invalid_confidence")
            self.assertEqual(issue["turn_index"], 1)
            self.assertEqual(issue["field_path"], "turns[0].confidence")
            self.assertEqual(issue["expected"], ["high", "medium", "low"])
            self.assertEqual(issue["actual"], "extreme")
            self.assertEqual(report["issues_by_turn"][0]["turn_index"], 1)
            self.assertTrue(report["issues_by_turn"][0]["blocking"])
            self.assertEqual(report["issues_by_turn"][0]["blocking_issue_count"], 1)
            self.assertEqual(report["issues_by_turn"][0]["non_blocking_issue_count"], 0)
            self.assertEqual(report["issues_by_turn"][0]["priority_rank"], 1)
            self.assertEqual(report["issues_by_turn"][0]["codes"], ["slot_invalid_confidence"])
            self.assertEqual(report["issues_by_section"][0]["section"], "turns")
            self.assertTrue(report["issues_by_section"][0]["blocking"])
            self.assertEqual(report["issues_by_section"][0]["priority_rank"], 40)
            self.assertEqual(report["issues_by_section"][0]["codes"], ["slot_invalid_confidence"])
            self.assertEqual(report["recommended_repair_order"][0]["scope_type"], "turn")
            self.assertEqual(report["recommended_repair_order"][0]["scope_id"], 1)
            self.assertEqual(report["recommended_repair_order"][0]["priority_rank"], 1)
            self.assertEqual(report["recommended_repair_order"][0]["primary_action"], "normalize_confidence")

    def test_main_validate_dispatch_payload_localizes_synthesis_error(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            session_spec_file = root / "session-spec.json"
            payload_file = root / "dispatch-invalid-synthesis.json"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-session-spec",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--session-spec-output",
                        str(session_spec_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(main.main(), 0)

            session_spec = json.loads(session_spec_file.read_text(encoding="utf-8"))
            payload = {
                "prompt": "Imported harness run brief.",
                "project_root": str(root),
                "session_spec": session_spec,
                "turns": [
                    {
                        "stage": "survey",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "judgment": "Survey judgment.",
                        "evidence": ["Survey evidence"],
                        "tradeoff": "Survey tradeoff.",
                        "objection": "Survey objection.",
                        "needs_verification": ["Survey verify"],
                        "confidence": "high",
                    },
                    {
                        "stage": "review",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "judgment": "Review judgment.",
                        "evidence": ["Review evidence"],
                        "tradeoff": "Review tradeoff.",
                        "objection": "Review objection.",
                        "needs_verification": ["Review verify"],
                        "confidence": "medium",
                    },
                ],
                "synthesis": {
                    "title": "",
                    "summary": "Imported run stays schema compatible.",
                    "decision": "Accept imported turns and preserve trace shape.",
                    "key_decisions": ["Keep six-slot contract stable."],
                    "strongest_objections": [
                        {"skill": "FastAPI", "objection": "Do not blur boundaries.", "severity": "medium"}
                    ],
                    "next_steps": ["Add ingestion for external harness outputs."],
                    "open_questions": ["Should strict hash check be default?"],
                    "skill_notes": [{"skill": "FastAPI", "note": "Keep contract explicit."}],
                },
            }
            payload_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    ["main.py", "--validate-dispatch-payload", str(payload_file)],
                ),
                patch("builtins.print") as mocked_print,
            ):
                exit_code = main.main()

            self.assertEqual(exit_code, 2)
            report = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(report["status"], "fail")
            issue = report["issues"][0]
            self.assertEqual(issue["code"], "synthesis_payload_invalid")
            self.assertEqual(issue["field_path"], "synthesis.title")
            self.assertEqual(issue["expected"], {"type": "string", "non_empty": True})
            self.assertEqual(issue["actual"], "")
            self.assertEqual(report["issues_by_turn"], [])
            self.assertEqual(report["issues_by_section"][0]["section"], "synthesis")
            self.assertTrue(report["issues_by_section"][0]["blocking"])
            self.assertEqual(report["issues_by_section"][0]["priority_rank"], 50)
            self.assertEqual(report["issues_by_section"][0]["codes"], ["synthesis_payload_invalid"])
            self.assertEqual(report["recommended_repair_order"][0]["scope_type"], "section")
            self.assertEqual(report["recommended_repair_order"][0]["scope_id"], "synthesis")
            self.assertEqual(report["recommended_repair_order"][0]["priority_rank"], 50)
            self.assertEqual(report["recommended_repair_order"][0]["primary_action"], "fill_synthesis_contract")

    def test_main_ingest_session_run_writes_trace_artifacts(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            session_spec_file = root / "session-spec.json"
            ingest_file = root / "ingest.json"
            output_root = root / "traces" / "raw"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-session-spec",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--session-spec-output",
                        str(session_spec_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(main.main(), 0)

            session_spec = json.loads(session_spec_file.read_text(encoding="utf-8"))
            ingest_payload = {
                "prompt": "Imported harness run brief.",
                "project_root": str(root),
                "shared_brief": "Imported from harness.",
                "session_spec": session_spec,
                "turns": [
                    {
                        "stage": "survey",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "message": "Survey message",
                        "judgment": "Survey judgment.",
                        "evidence": ["Survey evidence"],
                        "tradeoff": "Survey tradeoff.",
                        "objection": "Survey objection.",
                        "needs_verification": ["Survey verify"],
                        "confidence": "high",
                    },
                    {
                        "stage": "review",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "message": "Review message",
                        "judgment": "Review judgment.",
                        "evidence": ["Review evidence"],
                        "tradeoff": "Review tradeoff.",
                        "objection": "Review objection.",
                        "needs_verification": ["Review verify"],
                        "confidence": "medium",
                    },
                ],
                "synthesis": {
                    "title": "Imported synthesis",
                    "summary": "Imported run stays schema compatible.",
                    "decision": "Accept imported turns and preserve trace shape.",
                    "key_decisions": ["Keep six-slot contract stable."],
                    "strongest_objections": [
                        {
                            "skill": "FastAPI",
                            "objection": "Do not blur transport contract boundaries.",
                            "severity": "medium",
                        }
                    ],
                    "next_steps": ["Add ingestion for external harness outputs."],
                    "open_questions": ["Should strict hash check be default?"],
                    "skill_notes": [{"skill": "FastAPI", "note": "Keep contract explicit."}],
                },
            }
            ingest_file.write_text(json.dumps(ingest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--ingest-session-run",
                        str(ingest_file),
                        "--output-root",
                        str(output_root),
                        "--ingest-directory-name",
                        "imported-run",
                    ],
                ),
                patch("builtins.print") as mocked_print,
            ):
                exit_code = main.main()

            self.assertEqual(exit_code, 0)
            run_dir = Path(mocked_print.call_args_list[-1].args[0])
            self.assertTrue((run_dir / "run.json").exists())
            self.assertTrue((run_dir / "transcript.md").exists())
            self.assertTrue((run_dir / "result.md").exists())
            self.assertTrue((run_dir / "debate.md").exists())

            payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["task"]["prompt"], "Imported harness run brief.")
            self.assertEqual(payload["admission"]["status"], "accept")
            self.assertEqual(payload["harness"]["source_of_truth"], "SKILL.md")
            self.assertEqual(payload["harness"]["selected_skill_slugs"], ["fastapi"])
            self.assertEqual([turn["stage"] for turn in payload["turns"]], ["survey", "review"])
            self.assertEqual(payload["synthesis"]["title"], "Imported synthesis")
            debate = (run_dir / "debate.md").read_text(encoding="utf-8")
            self.assertIn("selected_skill_slugs: fastapi", debate)
            self.assertIn("handoff_path:", debate)

    def test_main_ingest_session_run_hash_guard_and_override(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_dir = _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            session_spec_file = root / "session-spec.json"
            ingest_file = root / "ingest.json"
            output_root = root / "traces" / "raw"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-session-spec",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--session-spec-output",
                        str(session_spec_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(main.main(), 0)

            session_spec = json.loads(session_spec_file.read_text(encoding="utf-8"))
            ingest_payload = {
                "prompt": "Imported harness run brief.",
                "project_root": str(root),
                "session_spec": session_spec,
                "turns": [
                    {
                        "stage": "survey",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "judgment": "Survey judgment.",
                        "evidence": ["Survey evidence"],
                        "tradeoff": "Survey tradeoff.",
                        "objection": "Survey objection.",
                        "needs_verification": ["Survey verify"],
                        "confidence": "high",
                    },
                    {
                        "stage": "review",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "judgment": "Review judgment.",
                        "evidence": ["Review evidence"],
                        "tradeoff": "Review tradeoff.",
                        "objection": "Review objection.",
                        "needs_verification": ["Review verify"],
                        "confidence": "medium",
                    },
                ],
                "synthesis": {
                    "title": "Imported synthesis",
                    "summary": "Imported run stays schema compatible.",
                    "decision": "Accept imported turns and preserve trace shape.",
                    "key_decisions": ["Keep six-slot contract stable."],
                    "strongest_objections": [
                        {"skill": "FastAPI", "objection": "Do not blur boundaries.", "severity": "medium"}
                    ],
                    "next_steps": ["Add ingestion for external harness outputs."],
                    "open_questions": ["Should strict hash check be default?"],
                    "skill_notes": [{"skill": "FastAPI", "note": "Keep contract explicit."}],
                },
            }
            ingest_file.write_text(json.dumps(ingest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text(skill_file.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--ingest-session-run",
                        str(ingest_file),
                        "--output-root",
                        str(output_root),
                    ],
                ),
                patch("builtins.print"),
            ):
                with self.assertRaises(ValueError):
                    main.main()

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--ingest-session-run",
                        str(ingest_file),
                        "--output-root",
                        str(output_root),
                        "--ignore-hash-mismatch",
                    ],
                ),
                patch("builtins.print") as mocked_print,
            ):
                self.assertEqual(main.main(), 0)
            run_dir = Path(mocked_print.call_args_list[-1].args[0])
            self.assertTrue((run_dir / "failure-events.jsonl").exists())
            events = [
                json.loads(line)
                for line in (run_dir / "failure-events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["failure_code"], "prompt_hash_mismatch")
            self.assertEqual(events[0]["owner"], "redistill")

    def test_main_ingest_turn_count_mismatch_writes_failure_event(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            session_spec_file = root / "session-spec.json"
            ingest_file = root / "ingest-mismatch.json"
            output_root = root / "traces" / "raw"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-session-spec",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--session-spec-output",
                        str(session_spec_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(main.main(), 0)

            session_spec = json.loads(session_spec_file.read_text(encoding="utf-8"))
            ingest_payload = {
                "prompt": "Imported harness run brief.",
                "project_root": str(root),
                "session_spec": session_spec,
                "turns": [
                    {
                        "stage": "survey",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "judgment": "Survey judgment.",
                        "evidence": ["Survey evidence"],
                        "tradeoff": "Survey tradeoff.",
                        "objection": "Survey objection.",
                        "needs_verification": ["Survey verify"],
                        "confidence": "high",
                    }
                ],
                "synthesis": {
                    "title": "Imported synthesis",
                    "summary": "Imported run stays schema compatible.",
                    "decision": "Accept imported turns and preserve trace shape.",
                    "key_decisions": ["Keep six-slot contract stable."],
                    "strongest_objections": [
                        {"skill": "FastAPI", "objection": "Do not blur boundaries.", "severity": "medium"}
                    ],
                    "next_steps": ["Add ingestion for external harness outputs."],
                    "open_questions": ["Should strict hash check be default?"],
                    "skill_notes": [{"skill": "FastAPI", "note": "Keep contract explicit."}],
                },
            }
            ingest_file.write_text(json.dumps(ingest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--ingest-session-run",
                        str(ingest_file),
                        "--output-root",
                        str(output_root),
                        "--ingest-directory-name",
                        "mismatch-run",
                    ],
                ),
                patch("builtins.print"),
            ):
                with self.assertRaises(ValueError):
                    main.main()

            events_path = output_root / "mismatch-run" / "failure-events.jsonl"
            self.assertTrue(events_path.exists())
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["failure_code"], "schedule_turn_count_mismatch")
            self.assertEqual(events[0]["source_stage"], "ingest")

    def test_main_ingest_rejects_session_spec_turn_schedule_drift(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            session_spec_file = root / "session-spec.json"
            ingest_file = root / "ingest-drift.json"
            output_root = root / "traces" / "raw"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-session-spec",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--session-spec-output",
                        str(session_spec_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(main.main(), 0)

            session_spec = json.loads(session_spec_file.read_text(encoding="utf-8"))
            session_spec["turn_schedule"][1]["stage"] = "survey"
            ingest_payload = {
                "prompt": "Imported harness run brief.",
                "project_root": str(root),
                "session_spec": session_spec,
                "turns": [
                    {
                        "stage": "survey",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "judgment": "Survey judgment.",
                        "evidence": ["Survey evidence"],
                        "tradeoff": "Survey tradeoff.",
                        "objection": "Survey objection.",
                        "needs_verification": ["Survey verify"],
                        "confidence": "high",
                    },
                    {
                        "stage": "review",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "judgment": "Review judgment.",
                        "evidence": ["Review evidence"],
                        "tradeoff": "Review tradeoff.",
                        "objection": "Review objection.",
                        "needs_verification": ["Review verify"],
                        "confidence": "medium",
                    },
                ],
                "synthesis": {
                    "title": "Imported synthesis",
                    "summary": "Imported run stays schema compatible.",
                    "decision": "Accept imported turns and preserve trace shape.",
                    "key_decisions": ["Keep six-slot contract stable."],
                    "strongest_objections": [
                        {"skill": "FastAPI", "objection": "Do not blur boundaries.", "severity": "medium"}
                    ],
                    "next_steps": ["Add ingestion for external harness outputs."],
                    "open_questions": ["Should strict hash check be default?"],
                    "skill_notes": [{"skill": "FastAPI", "note": "Keep contract explicit."}],
                },
            }
            ingest_file.write_text(json.dumps(ingest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--ingest-session-run",
                        str(ingest_file),
                        "--output-root",
                        str(output_root),
                        "--ingest-directory-name",
                        "drift-run",
                    ],
                ),
                patch("builtins.print"),
            ):
                with self.assertRaises(ValueError):
                    main.main()

            events_path = output_root / "drift-run" / "failure-events.jsonl"
            self.assertTrue(events_path.exists())
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["failure_code"], "schedule_turn_order_mismatch")
            self.assertEqual(events[0]["source_stage"], "ingest")

    def test_main_ingest_rewrites_reduction_slots_to_canonical_contract(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            session_spec_file = root / "session-spec.json"
            ingest_file = root / "ingest.json"
            output_root = root / "traces" / "raw"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-session-spec",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--session-spec-output",
                        str(session_spec_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(main.main(), 0)

            session_spec = json.loads(session_spec_file.read_text(encoding="utf-8"))
            session_spec["reduction_slots"] = ["foo", "bar"]
            ingest_payload = {
                "prompt": "Imported harness run brief.",
                "project_root": str(root),
                "session_spec": session_spec,
                "turns": [
                    {
                        "stage": "survey",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "judgment": "Survey judgment.",
                        "evidence": ["Survey evidence"],
                        "tradeoff": "Survey tradeoff.",
                        "objection": "Survey objection.",
                        "needs_verification": ["Survey verify"],
                        "confidence": "high",
                    },
                    {
                        "stage": "review",
                        "round_index": 1,
                        "skill_slug": "fastapi",
                        "judgment": "Review judgment.",
                        "evidence": ["Review evidence"],
                        "tradeoff": "Review tradeoff.",
                        "objection": "Review objection.",
                        "needs_verification": ["Review verify"],
                        "confidence": "medium",
                    },
                ],
                "synthesis": {
                    "title": "Imported synthesis",
                    "summary": "Imported run stays schema compatible.",
                    "decision": "Accept imported turns and preserve trace shape.",
                    "key_decisions": ["Keep six-slot contract stable."],
                    "strongest_objections": [
                        {"skill": "FastAPI", "objection": "Do not blur boundaries.", "severity": "medium"}
                    ],
                    "next_steps": ["Add ingestion for external harness outputs."],
                    "open_questions": ["Should strict hash check be default?"],
                    "skill_notes": [{"skill": "FastAPI", "note": "Keep contract explicit."}],
                },
            }
            ingest_file.write_text(json.dumps(ingest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--ingest-session-run",
                        str(ingest_file),
                        "--output-root",
                        str(output_root),
                        "--ingest-directory-name",
                        "canonical-slots-run",
                    ],
                ),
                patch("builtins.print") as mocked_print,
            ):
                self.assertEqual(main.main(), 0)
            run_dir = Path(mocked_print.call_args_list[-1].args[0])
            payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(
                payload["harness"]["reduction_slots"],
                ["judgment", "evidence", "tradeoff", "objection", "needs_verification", "confidence"],
            )

    def test_main_ingest_missing_session_spec_path_writes_payload_invalid_failure(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ingest_file = root / "ingest-missing-session-spec.json"
            output_root = root / "traces" / "raw"
            ingest_payload = {
                "prompt": "Imported harness run brief.",
                "session_spec_path": "missing-session-spec.json",
                "turns": [],
                "synthesis": {},
            }
            ingest_file.write_text(json.dumps(ingest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--ingest-session-run",
                        str(ingest_file),
                        "--output-root",
                        str(output_root),
                        "--ingest-directory-name",
                        "missing-session-spec-run",
                    ],
                ),
                patch("builtins.print"),
            ):
                with self.assertRaises(ValueError):
                    main.main()

            events_path = output_root / "missing-session-spec-run" / "failure-events.jsonl"
            self.assertTrue(events_path.exists())
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["failure_code"], "ingest_payload_invalid")
            self.assertEqual(events[0]["owner"], "harness")

    def test_main_ingest_invalid_json_writes_payload_invalid_failure(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ingest_file = root / "ingest-invalid.json"
            output_root = root / "traces" / "raw"
            ingest_file.write_text('{"prompt": "broken"', encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--ingest-session-run",
                        str(ingest_file),
                        "--output-root",
                        str(output_root),
                        "--ingest-directory-name",
                        "invalid-json-run",
                    ],
                ),
                patch("builtins.print"),
            ):
                with self.assertRaises(ValueError):
                    main.main()

            events_path = output_root / "invalid-json-run" / "failure-events.jsonl"
            self.assertTrue(events_path.exists())
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["failure_code"], "ingest_payload_invalid")
            self.assertEqual(events[0]["source_stage"], "ingest")

    def test_main_ingest_missing_payload_file_writes_payload_invalid_failure(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ingest_file = root / "missing-ingest.json"
            output_root = root / "traces" / "raw"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--ingest-session-run",
                        str(ingest_file),
                        "--output-root",
                        str(output_root),
                        "--ingest-directory-name",
                        "missing-payload-run",
                    ],
                ),
                patch("builtins.print"),
            ):
                with self.assertRaises(ValueError):
                    main.main()

            events_path = output_root / "missing-payload-run" / "failure-events.jsonl"
            self.assertTrue(events_path.exists())
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["failure_code"], "ingest_payload_invalid")
            self.assertEqual(events[0]["source_stage"], "ingest")

    def test_main_ingest_non_list_turns_writes_payload_invalid_failure(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            session_spec_file = root / "session-spec.json"
            ingest_file = root / "ingest-invalid-turns.json"
            output_root = root / "traces" / "raw"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-session-spec",
                        "--prompt",
                        "Review API contracts.",
                        "--skills",
                        "fastapi",
                        "--skill-root",
                        str(root / "skills"),
                        "--session-spec-output",
                        str(session_spec_file),
                    ],
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(main.main(), 0)

            session_spec = json.loads(session_spec_file.read_text(encoding="utf-8"))
            ingest_payload = {
                "prompt": "Imported harness run brief.",
                "project_root": str(root),
                "session_spec": session_spec,
                "turns": {"unexpected": "object"},
                "synthesis": {
                    "title": "Imported synthesis",
                    "summary": "Imported run stays schema compatible.",
                    "decision": "Accept imported turns and preserve trace shape.",
                    "key_decisions": ["Keep six-slot contract stable."],
                    "strongest_objections": [
                        {"skill": "FastAPI", "objection": "Do not blur boundaries.", "severity": "medium"}
                    ],
                    "next_steps": ["Add ingestion for external harness outputs."],
                    "open_questions": ["Should strict hash check be default?"],
                    "skill_notes": [{"skill": "FastAPI", "note": "Keep contract explicit."}],
                },
            }
            ingest_file.write_text(json.dumps(ingest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--ingest-session-run",
                        str(ingest_file),
                        "--output-root",
                        str(output_root),
                        "--ingest-directory-name",
                        "invalid-turns-run",
                    ],
                ),
                patch("builtins.print"),
            ):
                with self.assertRaises(ValueError):
                    main.main()

            events_path = output_root / "invalid-turns-run" / "failure-events.jsonl"
            self.assertTrue(events_path.exists())
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["failure_code"], "ingest_payload_invalid")
            self.assertEqual(events[0]["source_stage"], "ingest")

    def test_main_summarize_failures_reads_per_run_events(self) -> None:
        import main
        from datetime import UTC, datetime
        from uuid import uuid4

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run-a"
            run_dir.mkdir(parents=True, exist_ok=True)
            event = {
                "taxonomy_version": "v1",
                "event_id": str(uuid4()),
                "observed_at": datetime.now(UTC).isoformat(),
                "run_ref": str(run_dir / "run.json"),
                "source_stage": "ingest",
                "failure_code": "prompt_hash_mismatch",
                "layer": "redistill",
                "deterministic": True,
                "repro_ref": str(run_dir / "input.json"),
                "skill_slugs": ["fastapi"],
                "owner": "redistill",
                "action": "redistill_request",
                "severity": "medium",
                "contract_version": "harness.v1",
            }
            (run_dir / "failure-events.jsonl").write_text(
                json.dumps(event, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--summarize-failures",
                        "--failure-root",
                        str(root),
                        "--window-days",
                        "7",
                    ],
                ),
                patch("builtins.print") as mocked_print,
            ):
                exit_code = main.main()

            self.assertEqual(exit_code, 0)
            payload = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(payload["summary"]["event_count"], 1)
            self.assertEqual(payload["summary"]["by_code"][0]["key"], "prompt_hash_mismatch")

    def test_main_propose_redistill_dry_run(self) -> None:
        import main
        from datetime import UTC, datetime
        from uuid import uuid4

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_a = root / "run-a"
            run_b = root / "run-b"
            ticket_root = root / "tickets"
            run_a.mkdir(parents=True, exist_ok=True)
            run_b.mkdir(parents=True, exist_ok=True)
            ticket_root.mkdir(parents=True, exist_ok=True)
            observed = datetime.now(UTC).isoformat()

            base_event = {
                "taxonomy_version": "v1",
                "observed_at": observed,
                "source_stage": "ingest",
                "failure_code": "prompt_hash_mismatch",
                "layer": "redistill",
                "deterministic": True,
                "repro_ref": str(root / "input.json"),
                "skill_slugs": ["fastapi"],
                "owner": "redistill",
                "action": "redistill_request",
                "severity": "medium",
                "contract_version": "harness.v1",
            }
            first = dict(base_event)
            first["event_id"] = str(uuid4())
            first["run_ref"] = str(run_a / "run.json")
            second = dict(base_event)
            second["event_id"] = str(uuid4())
            second["run_ref"] = str(run_b / "run.json")
            (run_a / "failure-events.jsonl").write_text(json.dumps(first, ensure_ascii=False) + "\n", encoding="utf-8")
            (run_b / "failure-events.jsonl").write_text(
                json.dumps(second, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--propose-redistill",
                        "--failure-root",
                        str(root),
                        "--ticket-root",
                        str(ticket_root),
                        "--window-days",
                        "7",
                        "--daily-cap",
                        "3",
                        "--dry-run",
                    ],
                ),
                patch("builtins.print") as mocked_print,
            ):
                exit_code = main.main()

            self.assertEqual(exit_code, 0)
            payload = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(payload["ticket_count"], 1)
            self.assertEqual(payload["tickets"][0]["skill_slug"], "fastapi")
            self.assertIsNone(payload["ticket_path"])

    def test_main_emit_redistill_worklist_from_ticket_file(self) -> None:
        import main
        from datetime import UTC, datetime
        from uuid import uuid4

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ticket_root = root / "tickets"
            ticket_root.mkdir(parents=True, exist_ok=True)
            day = datetime.now(UTC).strftime("%Y-%m-%d")
            ticket = {
                "ticket_version": "v1",
                "ticket_id": str(uuid4()),
                "created_at": datetime.now(UTC).isoformat(),
                "skill_slug": "fastapi",
                "failure_code": "prompt_hash_mismatch",
                "window_days": 7,
                "frequency": 2,
                "max_severity": "medium",
                "sample_event_refs": [],
                "reason": "demo",
            }
            (ticket_root / f"{day}.jsonl").write_text(json.dumps(ticket, ensure_ascii=False) + "\n", encoding="utf-8")
            worklist_root = root / "worklists"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--emit-redistill-worklist",
                        "--ticket-root",
                        str(ticket_root),
                        "--ticket-day",
                        day,
                        "--worklist-root",
                        str(worklist_root),
                    ],
                ),
                patch("builtins.print") as mocked_print,
            ):
                exit_code = main.main()

            self.assertEqual(exit_code, 0)
            payload = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(payload["ticket_count"], 1)
            self.assertEqual(payload["work_item_count"], 1)
            self.assertIsNotNone(payload["worklist_path"])
            self.assertTrue(Path(payload["worklist_path"]).exists())
            self.assertEqual(payload["work_items"][0]["skill_slug"], "fastapi")

    def test_main_execute_redistill_worklist_is_idempotent(self) -> None:
        import main
        from datetime import UTC, datetime
        from uuid import uuid4

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            day = datetime.now(UTC).strftime("%Y-%m-%d")
            worklist_root = root / "worklists"
            worklist_root.mkdir(parents=True, exist_ok=True)
            repo_root = Path(main.__file__).resolve().parent
            work_item = {
                "work_version": "v1",
                "work_id": str(uuid4()),
                "created_at": datetime.now(UTC).isoformat(),
                "ticket_id": "demo-ticket",
                "skill_slug": "fastapi",
                "failure_code": "prompt_hash_mismatch",
                "failure_reason": "demo",
                "target_skill_file": str(repo_root / "skills" / "fastapi" / "SKILL.md"),
                "authoring_skill_file": str(repo_root / "authoring" / "project-incarnation" / "SKILL.md"),
                "objective": "demo",
                "constraints": [],
                "suggested_command": "demo",
                "prompt_template": "demo",
            }
            (worklist_root / f"{day}.jsonl").write_text(json.dumps(work_item, ensure_ascii=False) + "\n", encoding="utf-8")
            execution_root = root / "executions"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--execute-redistill-worklist",
                        "--worklist-root",
                        str(worklist_root),
                        "--worklist-day",
                        day,
                        "--execution-root",
                        str(execution_root),
                    ],
                ),
                patch("builtins.print") as mocked_print,
            ):
                first_exit = main.main()
            self.assertEqual(first_exit, 0)
            first_payload = json.loads(mocked_print.call_args_list[-1].args[0])
            self.assertEqual(first_payload["prepared_count"], 1)
            self.assertEqual(first_payload["skipped_count"], 0)
            self.assertIsNotNone(first_payload["record_path"])

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--execute-redistill-worklist",
                        "--worklist-root",
                        str(worklist_root),
                        "--worklist-day",
                        day,
                        "--execution-root",
                        str(execution_root),
                    ],
                ),
                patch("builtins.print") as mocked_print_again,
            ):
                second_exit = main.main()
            self.assertEqual(second_exit, 0)
            second_payload = json.loads(mocked_print_again.call_args_list[-1].args[0])
            self.assertEqual(second_payload["prepared_count"], 0)
            self.assertEqual(second_payload["skipped_count"], 1)

    def test_run_echo_prints_incremental_skill_runtime_logs(self) -> None:
        import main

        stream = StringIO()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Demo\n\nRuntime project snapshot.", encoding="utf-8")
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            _write_skill(
                root,
                "do-things-that-dont-scale",
                title="Do Things That Don't Scale",
                description="Early growth method skill.",
            )
            main.run(
                prompt="Design the first skill runtime harness.",
                output_root=root / "traces" / "raw",
                client=FakeClient(),
                echo=True,
                stream=stream,
                repo_root=root,
                project_root=root,
                skill_root=root / "skills",
            )

        output = stream.getvalue()
        self.assertIn("## survey (round 1/1)", output)
        self.assertIn("## review (round 1/1)", output)
        self.assertIn("## synthesis", output)
        self.assertIn("- judgment:", output)

    def test_prepare_session_gate_outcomes_matrix(self) -> None:
        import main
        from src.councilkit.admission import prepare_session

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(5):
                _write_skill(
                    root,
                    f"skill-{index}",
                    title=f"Skill {index}",
                    description=f"Skill {index} handles api contract review.",
                )
            specs = main.load_skill_specs(root, root / "skills")

            accepted = prepare_session(
                skill_specs=specs[:1],
                prompt="Review API contract decisions.",
                explicit_skill_selection=True,
            )
            warned = prepare_session(
                skill_specs=specs[:4],
                prompt="Review API contract decisions.",
                explicit_skill_selection=True,
            )
            blocked = prepare_session(
                skill_specs=specs,
                prompt="Review API contract decisions.",
                explicit_skill_selection=True,
            )
            clarification = prepare_session(
                skill_specs=[],
                prompt="Review API contract decisions.",
                explicit_skill_selection=True,
            )

            self.assertEqual(accepted.status, "accept")
            self.assertEqual(warned.status, "accept_with_warning")
            self.assertEqual(blocked.status, "out_of_scope")
            self.assertEqual(clarification.status, "needs_clarification")

    def test_prepare_session_requires_non_zero_match_when_selection_is_implicit(self) -> None:
        import main
        from src.councilkit.admission import prepare_session

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            _write_skill(
                root,
                "do-things-that-dont-scale",
                title="Do Things That Don't Scale",
                description="Early growth method skill.",
            )
            specs = main.load_skill_specs(root, root / "skills")
            result = prepare_session(
                skill_specs=specs,
                prompt="astronomy telescope galaxy orbital mechanics",
                explicit_skill_selection=False,
            )
            self.assertEqual(result.status, "needs_clarification")
            self.assertEqual(result.selected_skills, ())

    def test_run_blocks_out_of_scope_when_selected_skills_exceed_hard_cap(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Demo\n\nRuntime project snapshot.", encoding="utf-8")
            selected: list[str] = []
            for index in range(5):
                slug = f"skill-{index}"
                selected.append(slug)
                _write_skill(
                    root,
                    slug,
                    title=f"Skill {index}",
                    description=f"Skill {index} handles api contract review.",
                )

            run_dir = main.run(
                prompt="Review API contract decisions.",
                output_root=root / "traces" / "raw",
                client=FakeClient(),
                repo_root=root,
                project_root=root,
                skill_root=root / "skills",
                skills=selected,
            )
            payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["admission"]["status"], "out_of_scope")
            self.assertEqual(payload["harness"]["admission_status"], "out_of_scope")
            self.assertEqual(len(payload["harness"]["selected_skill_slugs"]), 4)
            self.assertEqual(len(payload["turns"]), 0)
            self.assertEqual(payload["synthesis"]["title"], "Session blocked by admission gate")
            events_path = run_dir / "failure-events.jsonl"
            self.assertTrue(events_path.exists())
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["failure_code"], "admission_out_of_scope")
            self.assertEqual(events[0]["owner"], "harness")

    def test_review_context_frame_is_response_shaped(self) -> None:
        import main
        from src.councilkit.models import SkillInstance, TurnRecord, TurnResult
        from src.councilkit.modes.review import build_context_frame

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            spec = main.load_skill_specs(root, root / "skills")[0]
            instance = SkillInstance(spec=spec, instance_id="fastapi-instance")

            survey_frame = build_context_frame(
                skill=instance,
                stage="survey",
                round_index=1,
                total_rounds=1,
                project_context="Project root: demo",
                prompt="Review API contracts.",
                turns=[],
            )
            prior_turn = TurnRecord(
                stage="survey",
                round_index=1,
                skill_instance_id="fastapi-instance",
                skill_name="FastAPI",
                message="Survey message.",
                result=TurnResult(
                    judgment="Survey judgment.",
                    evidence=("Survey evidence.",),
                    tradeoff="Survey tradeoff.",
                    objection="Survey objection.",
                    needs_verification=("Survey verification.",),
                    confidence="high",
                ),
            )
            review_frame = build_context_frame(
                skill=instance,
                stage="review",
                round_index=1,
                total_rounds=1,
                project_context="Project root: demo",
                prompt="Review API contracts.",
                turns=[prior_turn],
            )

            self.assertIn("Stage ask: State your boundary", survey_frame.skill_brief)
            self.assertIn("Stage ask: Sharpen your strongest objection", review_frame.skill_brief)
            self.assertTrue(any("objection=Survey objection." in line for line in review_frame.prior_turns))

    def test_hero_demo_fixture_keeps_structural_invariants(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# CouncilKit\n\nHero demo fixture.", encoding="utf-8")
            _write_skill(root, "fastapi", title="FastAPI", description="Typed API boundary owner.")
            _write_skill(
                root,
                "do-things-that-dont-scale",
                title="Do Things That Don't Scale",
                description="Early growth method skill.",
            )
            run_dir = main.run(
                prompt="Review CouncilKit design tradeoffs.",
                output_root=root / "traces" / "raw",
                client=FakeClient(),
                repo_root=root,
                project_root=root,
                skill_root=root / "skills",
                skills=["fastapi", "do-things-that-dont-scale"],
            )
            distilled_dir = main.distill_trace_artifacts(run_dir, output_root=root / "traces" / "distilled")

            raw = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            distilled = json.loads((distilled_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(raw["admission"]["status"], "accept")
            self.assertEqual(raw["admission"]["selected_skills"], ["fastapi", "do-things-that-dont-scale"])
            self.assertEqual([turn["stage"] for turn in raw["turns"]], ["survey", "survey", "review", "review"])
            self.assertEqual(raw["source_kind"], "raw")
            self.assertEqual(distilled["source_kind"], "distilled")
            self.assertEqual(raw["admission"]["status"], distilled["admission"]["status"])
            self.assertEqual(raw["harness"]["version"], distilled["harness"]["version"])
            self.assertEqual(raw["harness"]["selected_skill_slugs"], ["fastapi", "do-things-that-dont-scale"])
            self.assertEqual(set(raw.keys()), set(distilled.keys()))

    def test_repository_hero_demo_assets_exist_and_preserve_contract(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        brief_path = repo_root / "examples" / "briefs" / "councilkit-hero-demo.md"
        raw_dir = repo_root / "traces" / "raw" / "councilkit-hero-demo"
        distilled_dir = repo_root / "traces" / "distilled" / "councilkit-hero-demo"

        self.assertTrue(brief_path.exists())
        self.assertTrue((raw_dir / "run.json").exists())
        self.assertTrue((raw_dir / "transcript.md").exists())
        self.assertTrue((raw_dir / "result.md").exists())
        self.assertTrue((raw_dir / "debate.md").exists())
        self.assertTrue((distilled_dir / "run.json").exists())
        self.assertTrue((distilled_dir / "transcript.md").exists())
        self.assertTrue((distilled_dir / "result.md").exists())
        self.assertTrue((distilled_dir / "debate.md").exists())

        raw = json.loads((raw_dir / "run.json").read_text(encoding="utf-8"))
        distilled = json.loads((distilled_dir / "run.json").read_text(encoding="utf-8"))

        self.assertEqual(raw["source_kind"], "raw")
        self.assertEqual(distilled["source_kind"], "distilled")
        self.assertEqual(raw["admission"]["status"], "accept")
        self.assertEqual(raw["admission"]["selected_skills"], ["fastapi", "do-things-that-dont-scale"])
        self.assertEqual(distilled["admission"]["status"], "accept")
        self.assertEqual(
            distilled["admission"]["selected_skills"],
            ["fastapi", "do-things-that-dont-scale"],
        )
        self.assertEqual(raw["harness"]["source_of_truth"], "SKILL.md")
        self.assertEqual(raw["harness"]["admission_status"], "accept")
        self.assertEqual(raw["harness"]["selected_skill_slugs"], ["fastapi", "do-things-that-dont-scale"])
        self.assertEqual([turn["stage"] for turn in raw["turns"]], ["survey", "survey", "review", "review"])
        self.assertEqual([skill["slug"] for skill in raw["skills"]], ["fastapi", "do-things-that-dont-scale"])
        self.assertNotIn("examples/packs/fastapi/agent.json", raw["task"]["shared_brief"])
        self.assertNotIn("runs/example/run.json", raw["task"]["shared_brief"])
        self.assertIn("src/councilkit/runtime.py", raw["task"]["shared_brief"])
        self.assertEqual(set(raw.keys()), set(distilled.keys()))

    def test_repository_runtime_skills_include_newly_distilled_langgraph_and_llama_index(self) -> None:
        import main

        repo_root = Path(__file__).resolve().parents[1]
        skills = main.load_skill_specs(repo_root, repo_root / "skills")
        slugs = {skill.slug for skill in skills}

        self.assertIn("fastapi", slugs)
        self.assertIn("do-things-that-dont-scale", slugs)
        self.assertIn("langgraph", slugs)
        self.assertIn("llama-index", slugs)

    def test_repository_ingest_fixtures_validate_and_ingest(self) -> None:
        import main

        repo_root = Path(__file__).resolve().parents[1]
        session_spec_path = repo_root / "examples" / "ingest" / "session-spec.json"
        template_path = repo_root / "examples" / "ingest" / "dispatch-template.json"
        external_run_path = repo_root / "examples" / "ingest" / "external-run.json"

        self.assertTrue(session_spec_path.exists())
        self.assertTrue(template_path.exists())
        self.assertTrue(external_run_path.exists())

        session_spec = json.loads(session_spec_path.read_text(encoding="utf-8"))
        template = json.loads(template_path.read_text(encoding="utf-8"))
        external_run = json.loads(external_run_path.read_text(encoding="utf-8"))

        self.assertEqual(template["template_version"], "v1")
        self.assertEqual(template["session_spec"], session_spec)
        self.assertEqual(external_run["session_spec"], session_spec)
        self.assertEqual(template["session_spec"]["selected_skill_slugs"], ["fastapi", "do-things-that-dont-scale"])
        self.assertEqual(external_run["session_spec"]["selected_skill_slugs"], ["fastapi", "do-things-that-dont-scale"])
        self.assertEqual([turn["stage"] for turn in template["turns"]], ["survey", "survey", "review", "review"])
        self.assertEqual([turn["stage"] for turn in external_run["turns"]], ["survey", "survey", "review", "review"])

        with (
            patch.object(
                sys,
                "argv",
                ["main.py", "--validate-dispatch-payload", str(external_run_path)],
            ),
            patch("builtins.print") as mocked_print,
        ):
            validate_exit = main.main()
        self.assertEqual(validate_exit, 0)
        report = json.loads(mocked_print.call_args_list[-1].args[0])
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["checked_skills"], ["fastapi", "do-things-that-dont-scale"])

        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "traces" / "raw"
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--ingest-session-run",
                        str(external_run_path),
                        "--output-root",
                        str(output_root),
                        "--ingest-directory-name",
                        "example-ingest-run",
                    ],
                ),
                patch("builtins.print") as mocked_print_ingest,
            ):
                ingest_exit = main.main()
            self.assertEqual(ingest_exit, 0)
            run_dir = Path(mocked_print_ingest.call_args_list[-1].args[0])
            self.assertTrue((run_dir / "run.json").exists())
            self.assertTrue((run_dir / "debate.md").exists())
            payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["admission"]["status"], "accept")
            self.assertEqual(payload["harness"]["selected_skill_slugs"], ["fastapi", "do-things-that-dont-scale"])
            self.assertEqual([turn["stage"] for turn in payload["turns"]], ["survey", "survey", "review", "review"])
            self.assertEqual(payload["task"]["project_root"], str(repo_root.resolve()))

    def test_repository_runtime_triad_assets_exist_and_preserve_contract(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        brief_path = repo_root / "examples" / "briefs" / "councilkit-runtime-triad.md"
        raw_dir = repo_root / "traces" / "raw" / "councilkit-runtime-triad"
        distilled_dir = repo_root / "traces" / "distilled" / "councilkit-runtime-triad"

        self.assertTrue(brief_path.exists())
        self.assertTrue((raw_dir / "run.json").exists())
        self.assertTrue((raw_dir / "transcript.md").exists())
        self.assertTrue((raw_dir / "result.md").exists())
        self.assertTrue((raw_dir / "debate.md").exists())
        self.assertTrue((distilled_dir / "run.json").exists())
        self.assertTrue((distilled_dir / "transcript.md").exists())
        self.assertTrue((distilled_dir / "result.md").exists())
        self.assertTrue((distilled_dir / "debate.md").exists())

        raw = json.loads((raw_dir / "run.json").read_text(encoding="utf-8"))
        distilled = json.loads((distilled_dir / "run.json").read_text(encoding="utf-8"))

        self.assertEqual(raw["source_kind"], "raw")
        self.assertEqual(distilled["source_kind"], "distilled")
        self.assertEqual(raw["admission"]["status"], "accept")
        self.assertEqual(raw["admission"]["selected_skills"], ["fastapi", "langgraph", "llama-index"])
        self.assertEqual(raw["harness"]["selected_skill_slugs"], ["fastapi", "langgraph", "llama-index"])
        self.assertEqual([turn["stage"] for turn in raw["turns"]], ["survey", "survey", "survey", "review", "review", "review"])
        self.assertEqual([skill["slug"] for skill in raw["skills"]], ["fastapi", "langgraph", "llama-index"])
        self.assertNotIn("examples/packs/fastapi/agent.json", raw["task"]["shared_brief"])
        self.assertNotIn("runs/example/run.json", raw["task"]["shared_brief"])
        self.assertIn("src/councilkit/runtime.py", raw["task"]["shared_brief"])
        self.assertEqual(set(raw.keys()), set(distilled.keys()))

    def test_distill_trace_artifacts_preserve_schema_without_live_skill_files(self) -> None:
        import main

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "traces" / "raw" / "example-trace"
            raw_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "source_kind": "raw",
                "created_at": "20260409T120000Z",
                "task": {
                    "prompt": "Review the harness trace.",
                    "mode": "review",
                    "project_root": str(root / "demo-project"),
                    "shared_brief": "Project root: demo-project",
                    "tool_grants": [],
                },
                "skills": [
                    {
                        "instance_id": "fastapi-instance",
                        "slug": "fastapi",
                        "name": "FastAPI",
                        "description": "Typed API boundary owner.",
                        "tagline": "Type the contract first.",
                        "path": str(root / "missing-skill"),
                        "skill_file": str(root / "missing-skill" / "SKILL.md"),
                        "skill_mtime": 123.0,
                    }
                ],
                "turn_count": 3,
                "harness": {
                    "version": "v1",
                    "source_of_truth": "SKILL.md",
                    "prompt_contract": "SKILL.md acts as prompt, persona, and reasoning contract.",
                    "reduction_slots": [
                        "judgment",
                        "evidence",
                        "tradeoff",
                        "objection",
                        "needs_verification",
                        "confidence",
                    ],
                    "mode": "review",
                    "stage_order": ["survey", "review", "synthesis"],
                    "rounds_per_stage": {"survey": 1, "review": 1},
                    "selected_skill_slugs": ["fastapi"],
                    "loaded_skill_slugs": ["fastapi"],
                    "skills": [
                        {
                            "slug": "fastapi",
                            "name": "FastAPI",
                            "skill_file": str(root / "missing-skill" / "SKILL.md"),
                            "skill_mtime": 123.0,
                            "prompt_sha256": "demo-hash",
                        }
                    ],
                    "admission_status": "accept",
                },
                "turns": [
                    {
                        "stage": "survey",
                        "round_index": 1,
                        "skill_instance_id": "fastapi-instance",
                        "skill_name": "FastAPI",
                        "message": "The transport edge is loose. It needs a tighter contract. More detail should be dropped.",
                        "result": {
                            "judgment": "The request boundary is too loose. Tighten it before scaling. Keep the decision compact.",
                            "evidence": [
                                "Upload accepts arbitrary filenames from the client.",
                                "Startup errors are swallowed and the process keeps serving.",
                                "Async routes still call blocking work directly.",
                            ],
                            "tradeoff": "Loose contracts help fast iteration. They also hide failure modes.",
                            "objection": "Do not confuse a working route with a production-safe transport contract.",
                            "needs_verification": [
                                "Measure whether blocking calls dominate latency.",
                                "Confirm whether startup failures happen in production.",
                            ],
                            "confidence": "high",
                            "patch_proposals": [],
                        },
                    },
                    {
                        "stage": "review",
                        "round_index": 1,
                        "skill_instance_id": "fastapi-instance",
                        "skill_name": "FastAPI",
                        "message": "The review should stay compact. It should keep only the highest-signal point.",
                        "result": {
                            "judgment": "Fail fast on startup and tighten request models first.",
                            "evidence": [
                                "The current route models are under-specified.",
                                "Lifecycle guarantees are weaker than the endpoints suggest.",
                            ],
                            "tradeoff": "A stricter edge slows iteration slightly but makes failure modes inspectable.",
                            "objection": "Convenience is not a good reason to defer boundary work.",
                            "needs_verification": [
                                "Decide whether blocking work should move off the request path."
                            ],
                            "confidence": "medium",
                            "patch_proposals": [],
                        },
                    },
                ],
                "synthesis": {
                    "title": "Harness Review",
                    "summary": "The raw trace is useful but wordy. The distilled trace should keep the judgment surface intact while dropping excess list items.",
                    "decision": "Preserve the six slots and compress the projection.",
                    "key_decisions": [
                        "Keep the trace schema isomorphic.",
                        "Do not reintroduce bundle sidecars.",
                        "Preserve evidence paths.",
                        "Do not depend on live skill files.",
                    ],
                    "strongest_objections": [
                        {
                            "skill": "FastAPI",
                            "objection": "A distilled trace that needs live files is not a replayable artifact.",
                            "severity": "high",
                        }
                    ],
                    "next_steps": [
                        "Write the distilled artifact.",
                        "Verify the schema matches the raw trace.",
                        "Use the same renderers for transcript and result.",
                        "Keep the implementation deterministic.",
                    ],
                    "open_questions": [
                        "How aggressive should evidence compression be?",
                        "Should distilled traces ever rewrite language or only select it?",
                        "Do we need different presets later?",
                    ],
                    "skill_notes": [
                        {"skill": "FastAPI", "note": "Stay at the transport boundary."},
                        {"skill": "FastAPI", "note": "Keep the distilled trace replayable."},
                    ],
                },
                "model": None,
                "base_url": None,
            }
            (raw_dir / "run.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            distilled_dir = main.distill_trace_artifacts(raw_dir, output_root=root / "traces" / "distilled")

            self.assertEqual(distilled_dir.name, "example-trace")
            self.assertTrue((distilled_dir / "transcript.md").exists())
            self.assertTrue((distilled_dir / "result.md").exists())
            self.assertTrue((distilled_dir / "debate.md").exists())

            distilled = json.loads((distilled_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(distilled["source_kind"], "distilled")
            self.assertEqual(distilled["created_at"], payload["created_at"])
            self.assertEqual(distilled["skills"][0]["skill_mtime"], 123.0)
            self.assertEqual(distilled["harness"]["source_of_truth"], "SKILL.md")
            self.assertEqual(distilled["harness"]["admission_status"], "accept")
            self.assertEqual(distilled["harness"]["selected_skill_slugs"], ["fastapi"])
            self.assertEqual(len(distilled["turns"]), 2)
            self.assertLessEqual(len(distilled["turns"][0]["result"]["evidence"]), 2)
            self.assertLessEqual(len(distilled["turns"][0]["result"]["needs_verification"]), 1)
            self.assertLessEqual(len(distilled["synthesis"]["key_decisions"]), 3)
            self.assertLessEqual(len(distilled["synthesis"]["next_steps"]), 3)
            self.assertLessEqual(len(distilled["synthesis"]["open_questions"]), 2)
            debate = (distilled_dir / "debate.md").read_text(encoding="utf-8")
            self.assertIn("source_kind: distilled", debate)
            self.assertIn("No admission metadata captured.", debate)
            self.assertIn("missing-skill", debate)


if __name__ == "__main__":
    unittest.main()
