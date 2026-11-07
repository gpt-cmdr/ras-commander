"""Preserve feature and API-symbol bookmarks at the retired mapping URL."""
from pathlib import Path

from mkdocs.plugins import event_priority


REDIRECT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Redirecting</title>
<meta http-equiv="refresh" content="0; url=../../native-mapping-engine/">
<script>
var fragment = window.location.hash.slice(1);
try { fragment = decodeURIComponent(fragment); } catch (_) {}
var destination = fragment.startsWith("ras_commander.fim.")
    ? "../core/" : "../../native-mapping-engine/";
window.location.replace(destination + window.location.search + window.location.hash);
</script>
</head>
<body>
<p>Continue to the <a href="../../native-mapping-engine/">mapping guide</a>
or the <a href="../core/#mapping">class reference</a>.</p>
</body>
</html>
"""


@event_priority(-100)
def on_post_build(config, **kwargs):
    """Run after mkdocs-redirects creates the compatibility stub."""
    redirect = Path(config["site_dir"]) / "api/fim/index.html"
    if not redirect.is_file():
        raise RuntimeError("The mapping compatibility redirect was not generated")
    redirect.write_text(REDIRECT_HTML, encoding="utf-8")
