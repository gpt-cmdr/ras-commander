"""Verify retained test wheels and their declared engine source before installation."""
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
folder = root / "wheels"
build = json.loads((folder / "BUILD.json").read_text(encoding="utf-8"))
expected_names = {"ras2fim_engine-0.2.0-py3-none-manylinux_2_28_x86_64.whl",
                  "ras2fim_engine-0.2.0-py3-none-win_amd64.whl"}
assert set(build["artifact_sha256"]) == expected_names
assert {p.name for p in folder.glob("*.whl")} == expected_names
checksums = dict(line.split()[::-1] for line in (folder / "SHA256SUMS.txt").read_text().splitlines())
assert checksums == build["artifact_sha256"]
manifest = json.loads((root / "rust/step05/SOURCE_MANIFEST.json").read_text())
assert manifest["files"] == build["engine_source_files_sha256"]
for name, expected in build["engine_source_files_sha256"].items():
    content = (root / "rust/step05" / name).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(content).hexdigest() == expected, f"stale wheel source: {name}"
for name, expected in build["artifact_sha256"].items():
    path = folder / name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, f"wheel hash: {name}"
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        for notice in ["THIRD_PARTY_NOTICES.md", "licenses/ras2fim-LICENSE.txt", "licenses/scipy-LICENSE.txt"]:
            assert notice in archive.namelist(), (name, notice)
        executable = "ras2fim-batch.exe" if "win_amd64" in name else "ras2fim-batch"
        assert f"ras2fim_engine-0.2.0.data/scripts/{executable}" in archive.namelist()
print("Both wheel hashes, bundled notices and engine source fingerprints PASS")
