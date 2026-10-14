#!/usr/bin/env python3
"""Publish HEC-RAS release images to GHCR and record them in the package catalog.

Inputs are the outputs of the release builds: ``docker save`` archives
(``hec-ras-<role>_<version>_<build>.tar.gz`` with ``.sha256`` sidecars, from
``containers/hecras-wine-runtime/build_release_images.sh`` or the native recipe)
and, optionally, the SIFs converted from them (``hec-ras-<role>_<version>*.sif``
with ``.sha256`` sidecars, from ``containers/apptainer/build_sif_from_archive.sbatch``).

For each archive it verifies the sidecar, ``docker load``s it, tags it
``<registry>/hec-ras-<role>_<version>:<tag>``, pushes it, and records the pushed
digest. For each SIF it pushes ``<registry>/hec-ras-<role>-sif_<version>:<tag>``
with ``oras`` and records the manifest digest and the SIF's SHA-256. Then it
writes the ``ghcr``, ``sif`` and ``sif_sha256`` fields of
``ras_commander/resources/container_images.json``.

Without ``--execute`` it only prints the plan. ``--execute`` needs ``docker login
ghcr.io`` and ``oras login ghcr.io`` with ``write:packages``, and
``--confirm-terms-publication``: Wine images built by this repository carry the
HEC-RAS Terms and Conditions acceptance given at build time (6.1 and later), so
publishing them is a decision for the repository owner. New GHCR packages are
private until made public in the package settings.

Usage:
    python containers/publish/publish_ghcr.py --archives DIR [--sifs DIR] --tag TAG
        [--registry ghcr.io/gpt-cmdr] [--catalog PATH] [--execute --confirm-terms-publication]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROLES = ("wine-executor", "wine-precompute", "linux-unsteady")
_NAME = re.compile(r"hec-ras-(wine-executor|wine-precompute|linux-unsteady)_([5-7]\.[0-9]+(?:\.[0-9]+)?)(?=[_-]|\.sif$|\.tar\.gz$)")
_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / "ras_commander" / "resources" / "container_images.json"


def parse_name(name: str) -> tuple[str, str]:
    """Return ``(role, version)`` from a release archive or SIF file name."""
    match = _NAME.match(name)
    if not match:
        raise ValueError(f"not a release image file name: {name}")
    return match.group(1), match.group(2)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _sidecar(path: Path) -> str:
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"missing hash sidecar {sidecar}")
    value = sidecar.read_text(encoding="utf-8").split()[0]
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"malformed hash sidecar {sidecar}")
    return value


def plan(archives: Path, sifs: Path | None, registry: str, tag: str) -> list[dict]:
    """List the pushes, one per archive and SIF, refusing duplicates per role and release."""
    if not _TAG.fullmatch(tag):
        raise ValueError(f"invalid tag {tag!r}")
    registry = registry.rstrip("/")
    actions, seen = [], set()
    for path in sorted(archives.glob("hec-ras-*.tar.gz")):
        role, version = parse_name(path.name)
        if ("oci", role, version) in seen:
            raise ValueError(f"two archives for {role} {version} in {archives}")
        seen.add(("oci", role, version))
        actions.append({"kind": "oci", "role": role, "version": version, "file": path,
                        "sha256": _sidecar(path),
                        "target": f"{registry}/hec-ras-{role}_{version}:{tag}"})
    for path in sorted(sifs.glob("hec-ras-*.sif")) if sifs else []:
        role, version = parse_name(path.name)
        if ("sif", role, version) in seen:
            raise ValueError(f"two SIFs for {role} {version} in {sifs}")
        seen.add(("sif", role, version))
        actions.append({"kind": "sif", "role": role, "version": version, "file": path,
                        "sha256": _sidecar(path),
                        "target": f"{registry}/hec-ras-{role}-sif_{version}:{tag}"})
    return actions


def _run(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def push(action: dict) -> str:
    """Verify, push one action, and return the pushed digest (``sha256:...``)."""
    if _sha256(action["file"]) != action["sha256"]:
        raise ValueError(f"{action['file']} does not match its .sha256 sidecar")
    if action["kind"] == "oci":
        loaded = _run(["docker", "load", "--input", str(action["file"])])
        match = re.search(r"Loaded image(?: ID)?: (\S+)", loaded)
        if not match:
            raise RuntimeError(f"could not read the loaded image from: {loaded!r}")
        _run(["docker", "tag", match.group(1), action["target"]])
        output = _run(["docker", "push", action["target"]])
        digests = _DIGEST.findall(output.rsplit("digest:", 1)[-1])
    else:
        output = _run(["oras", "push", "--format", "json", action["target"],
                       f"{action['file'].name}:application/vnd.sylabs.sif.layer.v1.sif"])
        digests = [json.loads(output)["digest"]] if output.strip() else []
    if not digests:
        raise RuntimeError(f"no digest reported for {action['target']}")
    return digests[0]


def update_catalog(catalog: Path, pushed: list[dict]) -> None:
    """Write ``ghcr``/``sif``/``sif_sha256`` for each pushed role and release."""
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    entries = {(e["role"], e["hec_ras_version"]): e for e in payload["images"]}
    for action in pushed:
        key = (action["role"], action["version"])
        entry = entries.get(key)
        if entry is None:
            entry = {"role": key[0], "hec_ras_version": key[1], "ghcr": None, "sif": None,
                     "sif_sha256": None, "mirror": None}
            payload["images"].append(entry)
            entries[key] = entry
        repository = action["target"].rsplit(":", 1)[0]
        if action["kind"] == "oci":
            entry["ghcr"] = f"{repository}@{action['digest']}"
        else:
            entry["sif"] = f"oras://{repository}@{action['digest']}"
            entry["sif_sha256"] = action["sha256"]
    payload["images"].sort(key=lambda e: (ROLES.index(e["role"]),
                                          tuple(int(p) for p in e["hec_ras_version"].split("."))))
    catalog.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--archives", type=Path, required=True)
    parser.add_argument("--sifs", type=Path)
    parser.add_argument("--tag", required=True, help="for example the ras-commander release, 0.106.0")
    parser.add_argument("--registry", default="ghcr.io/gpt-cmdr")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-terms-publication", action="store_true")
    args = parser.parse_args(argv)
    actions = plan(args.archives, args.sifs, args.registry, args.tag)
    for action in actions:
        print(f"{action['kind']:3} {action['role']:15} {action['version']:6} {action['file'].name} -> {action['target']}")
    if not args.execute:
        print(f"dry run: {len(actions)} pushes planned; add --execute to publish")
        return 0
    if not args.confirm_terms_publication:
        print("refusing: Wine images carry a build-time HEC-RAS terms acceptance; "
              "pass --confirm-terms-publication once the repository owner approves", file=sys.stderr)
        return 2
    for action in actions:
        action["digest"] = push(action)
        print(f"pushed {action['target']}@{action['digest']}", flush=True)
    update_catalog(args.catalog, actions)
    print(f"updated {args.catalog}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
