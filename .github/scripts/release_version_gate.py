"""Release gate for the PyPI publish workflow.

Checks that a release tag, the version declared in the source tree, and the version inside the
built distributions all agree, before anything is uploaded.

Usage::

    python .github/scripts/release_version_gate.py source --tag v1.2.3 [--init PATH]
    python .github/scripts/release_version_gate.py dist --tag v1.2.3 --dist dist [--name NAME]
    python .github/scripts/release_version_gate.py declared     # prints v<declared version>

``declared`` is for pull-request dry runs, which have no tag: the build is then checked against
the version the source tree declares.

``source``: the tag must be ``vMAJOR.MINOR.PATCH`` (optionally with a PEP 440 pre/post/dev
suffix). The declared version is ``[project].version`` in ``pyproject.toml`` or, failing that,
``version="..."`` in ``setup.py``. ``--init`` names a module whose literal ``__version__`` must
agree as well.

``dist``: the folder must hold exactly one wheel and one sdist, and the ``Version`` (and,
with ``--name``, the ``Name``) in each one's metadata must match the tag.

Standard library only.
"""
import argparse
import email.parser
import re
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?)$")


def fail(message):
    print(f"release check failed: {message}", file=sys.stderr)
    sys.exit(1)


def tag_version(tag):
    m = TAG_RE.match(tag or "")
    if not m:
        fail(f"tag {tag!r} is not vMAJOR.MINOR.PATCH")
    return m.group(1)


def declared_version(root):
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
        if "version" in project:
            return project["version"], "pyproject.toml [project].version"
        if "version" in project.get("dynamic", []):
            fail("pyproject.toml declares a dynamic version; this check needs a literal one")
    setup = root / "setup.py"
    if setup.exists():
        found = re.findall(r'^\s*version\s*=\s*["\']([^"\']+)["\']', setup.read_text(encoding="utf-8"), re.M)
        if len(found) == 1:
            return found[0], "setup.py version="
        fail(f"setup.py has {len(found)} version= assignments; expected exactly one")
    fail("no literal version in pyproject.toml or setup.py")


def init_versions(path):
    text = Path(path).read_text(encoding="utf-8")
    found = re.findall(r'^\s*__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not found:
        fail(f"{path} has no literal __version__")
    return found


def check_source(args):
    want = tag_version(args.tag)
    got, where = declared_version(Path("."))
    if got != want:
        fail(f"tag {args.tag} does not match {where} = {got!r}")
    print(f"{where} = {got} matches tag {args.tag}")
    for path in args.init or []:
        for v in init_versions(path):
            if v != want:
                fail(f"tag {args.tag} does not match __version__ = {v!r} in {path}")
        print(f"__version__ in {path} matches tag {args.tag}")


def metadata_from_wheel(path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.fullmatch(r"[^/]+\.dist-info/METADATA", n)]
        if len(names) != 1:
            fail(f"{path.name} has {len(names)} dist-info METADATA files")
        return email.parser.Parser().parsestr(z.read(names[0]).decode("utf-8"))


def metadata_from_sdist(path):
    with tarfile.open(path) as t:
        names = [m for m in t.getmembers() if re.fullmatch(r"[^/]+/PKG-INFO", m.name)]
        if len(names) != 1:
            fail(f"{path.name} has {len(names)} top-level PKG-INFO files")
        return email.parser.Parser().parsestr(t.extractfile(names[0]).read().decode("utf-8"))


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def check_dist(args):
    want = tag_version(args.tag)
    dist = Path(args.dist)
    wheels, sdists = sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))
    others = [p.name for p in dist.iterdir() if p not in wheels and p not in sdists]
    if len(wheels) != 1 or len(sdists) != 1 or others:
        fail(f"expected one wheel and one sdist in {dist}, found wheels={[p.name for p in wheels]}, "
             f"sdists={[p.name for p in sdists]}, other={others}")
    for path, meta in ((wheels[0], metadata_from_wheel(wheels[0])), (sdists[0], metadata_from_sdist(sdists[0]))):
        if meta["Version"] != want:
            fail(f"{path.name} metadata Version {meta['Version']!r} does not match tag {args.tag}")
        if args.name and norm(meta["Name"]) != norm(args.name):
            fail(f"{path.name} metadata Name {meta['Name']!r} is not {args.name!r}")
        print(f"{path.name}: Name {meta['Name']}, Version {meta['Version']} matches tag {args.tag}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("source")
    s.add_argument("--tag", required=True)
    s.add_argument("--init", action="append", help="module with a literal __version__ to check too")
    d = sub.add_parser("dist")
    d.add_argument("--tag", required=True)
    d.add_argument("--dist", default="dist")
    d.add_argument("--name", help="expected distribution name")
    sub.add_parser("declared")
    args = ap.parse_args()
    if args.cmd == "declared":
        print("v" + declared_version(Path("."))[0])
        return
    (check_source if args.cmd == "source" else check_dist)(args)


if __name__ == "__main__":
    main()
