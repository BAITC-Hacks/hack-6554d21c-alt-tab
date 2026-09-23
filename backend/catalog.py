import json
from copy import deepcopy

from .config import ROOT


class Catalog:
    def __init__(self, root=ROOT):
        def read(name):
            return json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
        data = read("scenarios")
        self.scenarios = {s["scenario_id"]: s for s in data["scenarios"]}
        self.system_intents = data["system_intents"]
        self.slots = {s["name"]: s for s in read("slots")["slots"]}
        self.actions = {a["name"]: a for a in read("actions")["actions"]}
        self.knowledge = read("knowledge_base")
        self.mock = read("mock_backend")
        self.as_of_date = data["meta"]["as_of_date"]
        self.allowed_ids = set(self.scenarios) | {s["id"] for s in self.system_intents}
        if len(self.scenarios) != 40:
            raise ValueError("Expected all 40 Saqta scenarios")
        for scenario in self.scenarios.values():
            for name in scenario["slots"]["required"] + scenario["slots"]["optional"]:
                if name not in self.slots:
                    raise ValueError(f"Unknown slot {name}")
            for name in scenario["actions"]:
                if name not in self.actions:
                    raise ValueError(f"Unknown action {name}")

    def new_mock_state(self):
        return deepcopy(self.mock)
