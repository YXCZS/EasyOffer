from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from app.corpus.models import SourceManifest


class ManifestError(ValueError):
    pass


def load_manifest(path: str | Path) -> SourceManifest:
    import yaml

    manifest_path = Path(path).resolve()
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest = SourceManifest.model_validate(raw)
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
        raise ManifestError(str(exc)) from exc
    identities: set[tuple[str, str]] = set()
    for source in manifest.sources:
        source.manifest_dir = manifest_path.parent
        identity = (source.document_id, source.document_version)
        if identity in identities:
            raise ManifestError(f"duplicate source identity: {identity[0]}@{identity[1]}")
        identities.add(identity)
    return manifest

