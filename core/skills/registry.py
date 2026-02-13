from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SkillManifest:
    name: str
    version: str
    capabilities: list[str]
    inputs_schema: str
    outputs_schema: str
    side_effects: list[str]
    providers: list[str]
    scopes: str
    tests: list[str] | None = None


class SkillRegistry:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._manifests: dict[str, SkillManifest] = {}
        self.registry_path = skills_dir / "registry" / "registry.json"
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> None:
        self._manifests = {}
        for manifest_path in self.skills_dir.glob("*/manifest.json"):
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = SkillManifest(
                name=data["name"],
                version=data.get("version", "0.1.0"),
                capabilities=data.get("capabilities", []),
                inputs_schema=data.get("inputs_schema", ""),
                outputs_schema=data.get("outputs_schema", ""),
                side_effects=data.get("side_effects", []),
                providers=data.get("providers", []),
                scopes=data.get("scopes", "safe"),
                tests=data.get("tests"),
            )
            self._manifests[manifest.name] = manifest
        self._write_registry()

    def reload(self) -> None:
        self.load()

    def _write_registry(self) -> None:
        payload = {
            "skills": [m.__dict__ for m in self._manifests.values()],
        }
        self.registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_manifests(self) -> list[SkillManifest]:
        return list(self._manifests.values())

    def get_manifest(self, name: str) -> SkillManifest | None:
        return self._manifests.get(name)

    def get_skill(self, name: str):
        module_name = f"skills.{name}.skill"
        module = importlib.import_module(module_name)
        if hasattr(module, "skill"):
            return getattr(module, "skill")
        if hasattr(module, "run"):
            return module
        raise RuntimeError(f"Навык {name} не имеет точки входа")
