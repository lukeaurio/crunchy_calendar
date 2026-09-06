import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
N8N = ROOT / "n8n"
CONTRACTS = ROOT / "data" / "contracts"


def run_weekly_code(input_data: dict, config: dict) -> dict:
    workflow = json.loads((N8N / "weekly-forecast.json").read_text(encoding="utf-8"))
    code = next(node for node in workflow["nodes"] if node["name"] == "Build Forecast")
    code = code["parameters"]["jsCode"]
    payload = {"input": input_data, "config": config}
    harness = (
        "const payload=JSON.parse(require('fs').readFileSync(0,'utf8'));"
        "const $json=payload.input;"
        "const $=()=>({first:()=>({json:payload.config})});"
        f"const result=(()=>{{{code}}})();"
        "process.stdout.write(JSON.stringify(result[0].json));"
    )
    completed = subprocess.run(
        ["node", "-e", harness],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    return json.loads(completed.stdout)


class WorkflowTests(unittest.TestCase):
    def load_workflow(self, name: str) -> dict:
        return json.loads((N8N / name).read_text(encoding="utf-8"))

    def test_workflows_need_only_builtin_n8n_nodes(self):
        allowed = {
            "n8n-nodes-base.code",
            "n8n-nodes-base.html",
            "n8n-nodes-base.httpRequest",
            "n8n-nodes-base.scheduleTrigger",
        }
        for path in sorted(N8N.glob("*.json")):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(workflow["active"])
            self.assertTrue(workflow["nodes"])
            self.assertTrue(all(node["type"] in allowed for node in workflow["nodes"]))
            serialized = json.dumps(workflow).casefold()
            for forbidden in ("executecommand", "nix develop", "python -m", "/opt/", "/var/lib/"):
                self.assertNotIn(forbidden, serialized)

    def test_weekly_workflow_extracts_aligned_release_fields(self):
        workflow = self.load_workflow("weekly-forecast.json")
        extract = next(node for node in workflow["nodes"] if node["name"] == "Extract Releases")
        values = extract["parameters"]["extractionValues"]["values"]
        self.assertEqual(
            {value["key"] for value in values},
            {"titles", "source_starts_at", "urls", "source_episodes"},
        )
        self.assertTrue(all(value["returnArray"] for value in values))

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise n8n Code node JavaScript")
    def test_weekly_code_builds_the_forecast_contract(self):
        payload = {
            "fields": {
                "titles": ["Witch Hat Atelier Season 1", "Witch Hat Atelier Season 1 (English)"],
                "source_starts_at": [
                    "2026-08-24T14:00:00+00:00",
                    "2026-08-24T14:00:00+00:00",
                ],
                "urls": [
                    "https://www.crunchyroll.com/series/GTEST/witch-hat-atelier",
                    "https://www.crunchyroll.com/series/GTEST/witch-hat-atelier",
                ],
                "source_episodes": ["10", "10"],
            },
            "configuration": {
                "target_week_start": "2026-08-31",
                "source_week_start": "2026-08-24",
                "watching": ["Witch Hat Atelier"],
                "languages": {
                    "enabled": ["japanese", "english"],
                    "patterns": {"japanese": ["Japanese", "日本語"], "english": ["English"]},
                },
            },
        }
        report = run_weekly_code(payload["fields"], payload["configuration"])
        self.assertEqual(report["contract_version"], 1)
        self.assertEqual(report["week_start"], "2026-08-31")
        self.assertEqual(len(report["releases"]), 2)
        self.assertEqual({item["language"] for item in report["releases"]}, {"japanese", "english"})
        self.assertTrue(all(item["episode"] == 11 for item in report["releases"]))

    def test_contract_files_are_versioned_json_schemas(self):
        paths = sorted(CONTRACTS.glob("*.schema.json"))
        self.assertEqual(len(paths), 5)
        for path in paths:
            schema = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertTrue(schema["$id"].endswith(path.name))


if __name__ == "__main__":
    unittest.main()
