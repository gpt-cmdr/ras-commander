"""Execute the retired URL's routing script and check the normal build hook."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

pytest.importorskip("mkdocs")
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "mapping_redirect", ROOT / "scripts/mkdocs_mapping_redirect.py"
)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


@pytest.mark.parametrize("fragment, target", [
    ("", "/ras/native-mapping-engine/"),
    ("#depth-weighted-sloping-faces-engine-08", "/ras/native-mapping-engine/"),
    ("#ras_commander.fim.RasFim.RasFim.map_sloping_profiles", "/ras/api/core/"),
    ("#ras_commander.fim.FimPreparedSlopingModel", "/ras/api/core/"),
    ("#ras_commander%2Efim%2E_aoi.FimAoi", "/ras/api/core/"),
    ("#invalid%encoding", "/ras/native-mapping-engine/"),
])
def test_browser_fragment_routing(fragment, target):
    """Route each bookmark form to its rendered destination with its query intact."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute the redirect JavaScript")
    script = re.search(r"<script>(.*?)</script>", hook.REDIRECT_HTML, re.S).group(1)
    harness = """
const vm = require('node:vm');
const input = JSON.parse(process.argv[1]);
let result;
vm.runInNewContext(input.script, {window: {location: {
  hash: input.hash, search: '?from=bookmark', replace: value => {result = value;}
}}});
console.log(new URL(result, 'https://rascommander.info/ras/api/fim/').href);
"""
    result = subprocess.run(
        [node, "-e", harness, json.dumps({"script": script, "hash": fragment})],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == f"https://rascommander.info{target}?from=bookmark{fragment}"


def test_only_retired_stub_is_replaced(tmp_path):
    """Keep the compatibility hook from changing unrelated built pages."""
    retired = tmp_path / "api/fim/index.html"
    retired.parent.mkdir(parents=True)
    retired.write_text("generated redirect")
    other = tmp_path / "index.html"
    other.write_text("unchanged")
    hook.on_post_build({"site_dir": tmp_path})
    assert retired.read_text() == hook.REDIRECT_HTML
    assert other.read_text() == "unchanged"


def test_original_api_index_bookmark_is_preserved():
    """Retain one invisible target for bookmarks to the removed index heading."""
    page = (ROOT / "docs/api/index.md").read_text(encoding="utf-8")
    assert page.count('id="ras2fim-2d-flood-inundation-mapping-optional"') == 1


def test_build_routes_only_the_retired_mapping_page(tmp_path):
    """Verify actual plugin ordering and isolation in a strict MkDocs build."""
    pytest.importorskip("mkdocs_redirects")
    from mkdocs.commands.build import build
    from mkdocs.config import load_config
    import yaml

    docs = tmp_path / "docs"
    (docs / "api").mkdir(parents=True)
    (docs / "native-mapping-engine.md").write_text("# Mapping\n")
    (docs / "api/core.md").write_text("# Core\n")
    config_file = tmp_path / "mkdocs.yml"
    config_file.write_text(yaml.safe_dump({
        "site_name": "Redirect check", "strict": True,
        "docs_dir": str(docs), "site_dir": str(tmp_path / "site"),
        "hooks": [str(ROOT / "scripts/mkdocs_mapping_redirect.py")],
        "plugins": [{"redirects": {"redirect_maps": {
            "api/fim.md": "native-mapping-engine.md",
            "other.md": "native-mapping-engine.md",
        }}}],
    }))
    build(load_config(config_file=str(config_file)))
    assert (tmp_path / "site/api/fim/index.html").read_text() == hook.REDIRECT_HTML
    assert "ras_commander.fim." not in (tmp_path / "site/other/index.html").read_text()
