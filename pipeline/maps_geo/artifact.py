"""The build artifact in data/maps: manifest.json plus one JSON line per graph (instances.jsonl).

Pure data, no geo dependencies. `python -m maps_geo build` writes it; the exporter, the review
tooling and the tests read it back with `load`.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field


def instance_id(family: str, n: int, params: dict) -> str:
    """Stable id such as `map_country-n24-granularityprovinces-isoEC`."""
    return "-".join([family, f"n{n}"] + [f"{k}{params[k]}" for k in sorted(params)])


@dataclass
class Instance:
    id: str
    family: str                                    # "map_world" or "map_country"
    n: int
    params: dict                                   # {"policy": ...} or {"iso": ..., "granularity": ...}
    edges: list                                    # list[tuple[int, int]], u < v
    positions: list = field(default_factory=list)  # list[[x, y]] normalized 0..1
    labels: list = field(default_factory=list)     # list[str] unit names, index == vertex id
    codes: list = field(default_factory=list)      # list[str] unit codes, index == vertex id
    adjacency: dict = field(default_factory=dict)  # per-edge provenance

    def to_json(self) -> dict:
        d = asdict(self)
        d["edges"] = [list(e) for e in self.edges]
        return d

    @classmethod
    def from_json(cls, d: dict) -> "Instance":
        fields = cls.__dataclass_fields__
        inst = cls(**{k: v for k, v in d.items() if k in fields})
        inst.edges = [(int(u), int(v)) for (u, v) in inst.edges]
        return inst


@dataclass
class Manifest:
    version: str
    generator: str
    n_instances: int
    counts: dict                                   # family -> count
    extra: dict = field(default_factory=dict)      # build conventions: eps, sources, overrides, ...

    @classmethod
    def from_json(cls, d: dict) -> "Manifest":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def write(out_dir: str, manifest: Manifest, instances: list) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "instances.jsonl"), "w", encoding="utf-8") as f:
        for inst in instances:
            f.write(json.dumps(inst.to_json()) + "\n")
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(asdict(manifest), f, indent=2)
        f.write("\n")


def load(dataset_dir: str) -> tuple:
    """(Manifest, [Instance]) from an artifact directory."""
    with open(os.path.join(dataset_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = Manifest.from_json(json.load(f))
    with open(os.path.join(dataset_dir, "instances.jsonl"), encoding="utf-8") as f:
        instances = [Instance.from_json(json.loads(line)) for line in f if line.strip()]
    return manifest, instances
