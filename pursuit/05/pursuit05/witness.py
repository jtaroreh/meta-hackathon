from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


def encode_table(table: dict) -> dict:
    return {f"{k}:{','.join(str(v) for v in vals)}": bool(a)
            for (k, vals), a in table.items()}


def decode_table(obj: dict) -> dict:
    out = {}
    for key, a in obj.items():
        ks, _, rest = key.partition(":")
        vals = tuple(int(v) for v in rest.split(",") if v != "")
        out[(int(ks), vals)] = bool(a)
    return out


@dataclass
class Witness:
    witness_id: str
    goal: str
    regime: str
    cell_ids: list[str]
    arms: dict
    proposals: dict
    explanation: dict
    provider_id: str | None
    model_id: str | None
    source: str
    versions: dict
    seed: int
    timestamps: dict
    replay_command: str
    usage_total: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "witness_id": self.witness_id,
            "goal": self.goal,
            "regime": self.regime,
            "cell_ids": self.cell_ids,
            "arms": self.arms,
            "proposals": self.proposals,
            "explanation": self.explanation,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "source": self.source,
            "versions": self.versions,
            "seed": self.seed,
            "timestamps": self.timestamps,
            "replay_command": self.replay_command,
            "usage_total": self.usage_total,
        }

    @classmethod
    def from_dict(cls, obj: dict) -> Witness:
        need = {"witness_id", "goal", "regime", "cell_ids", "arms", "proposals",
                "explanation", "provider_id", "model_id", "source", "versions",
                "seed", "timestamps", "replay_command"}
        missing = need - set(obj)
        if missing:
            raise ValueError(f"witness misses keys: {sorted(missing)}")
        return cls(
            witness_id=obj["witness_id"],
            goal=obj["goal"],
            regime=obj["regime"],
            cell_ids=list(obj["cell_ids"]),
            arms=dict(obj["arms"]),
            proposals=dict(obj["proposals"]),
            explanation=dict(obj["explanation"]),
            provider_id=obj["provider_id"],
            model_id=obj["model_id"],
            source=obj["source"],
            versions=dict(obj["versions"]),
            seed=int(obj["seed"]),
            timestamps=dict(obj["timestamps"]),
            replay_command=obj["replay_command"],
            usage_total=dict(obj.get("usage_total", {})),
        )

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    @classmethod
    def read(cls, path: Path) -> Witness:
        try:
            obj = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"bad witness {path}: {exc}") from None
        if not isinstance(obj, dict):
            raise TypeError(f"bad witness {path}: not an object")
        return cls.from_dict(obj)


def arm_names(witness: Witness) -> list[str]:
    names: list[str] = []
    for cell_arms in witness.arms.values():
        for arm in cell_arms:
            if arm not in names:
                names.append(arm)
    return names
