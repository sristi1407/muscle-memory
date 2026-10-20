"""A minimal Capability Registry: save/load artifacts as JSON on disk."""
import os

from cua.schema import CapabilityArtifact


def save_capability(cap: CapabilityArtifact, directory: str = "capabilities") -> str:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{cap.id}.json")
    with open(path, "w") as f:
        f.write(cap.model_dump_json(indent=2))
    return path


def load_capability(path: str) -> CapabilityArtifact:
    with open(path) as f:
        return CapabilityArtifact.model_validate_json(f.read())
