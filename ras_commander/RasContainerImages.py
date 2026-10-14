"""Published HEC-RAS container images and a local SIF cache for Slurm/Apptainer.

``RasContainerImages`` answers two questions:

* Which image roles apply to a HEC-RAS release? Every Windows release from 4.0
  through 7.x can run under Wine (``wine-executor``). Wine preprocessing for a
  native Linux solve (``wine-precompute`` + ``linux-unsteady``) applies only
  where HEC published a Linux engine: 5.0.7 and 6.1 through 7.x.
* Which SIF should a job use? :meth:`resolve_sif` prefers a SIF the caller
  supplies, then a verified copy in the local cache, and pulls from the
  registry only when the policy allows. :meth:`ensure_sif_command` renders the
  same check-or-pull as an idempotent shell snippet for a cluster login host.

The catalog ships with the package (``resources/container_images.json``).
GitHub Container Registry (``ghcr.io/gpt-cmdr``) is the canonical home; until
an image is published there, the catalog's Docker Hub ``mirror`` digest is
used. Every reference is digest-pinned.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
from importlib.resources import files
from typing import Optional, Union

from .Decorators import log_call
from .LoggingConfig import get_logger

logger = get_logger(__name__)

CATALOG_SCHEMA = "ras-commander-container-images/v1"
CACHE_ENVIRONMENT = "RAS_COMMANDER_IMAGE_CACHE"
ROLES = ("wine-executor", "wine-precompute", "linux-unsteady")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DIGEST_REFERENCE = re.compile(r"[a-z0-9][a-z0-9._/:-]*@sha256:[0-9a-f]{64}\Z")
_INSTALL_FOLDER = re.compile(r"[4-7]\.[0-9]+(?:\.[0-9]+)?\Z")
# Aliases match RasPrj.get_ras_exe so the same spellings work everywhere.
_VERSION_ALIASES = {
    "4.1": "4.1.0", "41": "4.1.0", "410": "4.1.0", "40": "4.0",
    "50": "5.0", "501": "5.0.1", "503": "5.0.3", "504": "5.0.4", "505": "5.0.5",
    "506": "5.0.6", "507": "5.0.7",
    "60": "6.0", "61": "6.1", "6.1.0": "6.1", "62": "6.2", "63": "6.3", "631": "6.3.1",
    "6.4": "6.4.1", "64": "6.4.1", "641": "6.4.1", "65": "6.5", "66": "6.6",
    "70": "7.0", "701": "7.0.1", "7.1.0": "7.1", "71": "7.1",
}


def normalize_version(version: Union[str, float, int]) -> str:
    """Return the Windows install-folder name for a HEC-RAS release (4.0 to 7.x).

    Accepts the spellings ``RasPrj`` accepts: ``"4.1"`` → ``"4.1.0"``,
    ``"507"`` or ``"5.07"`` → ``"5.0.7"``, ``"66"`` → ``"6.6"``. Beta releases
    are not supported for containers.
    """
    text = str(version).strip()
    legacy = re.fullmatch(r"(\d)\.(\d{2})", text)
    if legacy:
        major, minor = legacy.groups()
        text = f"{major}.{minor[0]}.{int(minor[1])}"
    text = _VERSION_ALIASES.get(text, text)
    if not _INSTALL_FOLDER.fullmatch(text) or not (4, 0) <= _version_key(text)[:2] < (8, 0):
        raise ValueError(f"Unsupported HEC-RAS version for containers: {version!r} (expected 4.0 to 7.x)")
    return text


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def applicable_roles(version: Union[str, float, int]) -> tuple[str, ...]:
    """Return the image roles that apply to a HEC-RAS release.

    ``wine-executor`` (full Windows compute under Wine) applies to every
    release from 4.0 to 7.x. ``wine-precompute`` and ``linux-unsteady`` (Wine
    preprocessing then a native Linux solve) need a HEC Linux engine: 5.0.7,
    and 6.1 through 7.x.
    """
    folder = normalize_version(version)
    key = _version_key(folder)
    roles = ["wine-executor"]
    if folder == "5.0.7" or key >= (6, 1):
        roles += ["wine-precompute", "linux-unsteady"]
    return tuple(roles)


@dataclass(frozen=True)
class ContainerImage:
    """One catalog entry; ``reference`` is the digest-pinned OCI image to use."""

    role: str
    hec_ras_version: str
    ghcr: Optional[str]
    mirror: Optional[str]
    sif: Optional[str]
    sif_sha256: Optional[str]

    @property
    def reference(self) -> str:
        reference = self.ghcr or self.mirror
        if not reference:
            raise LookupError(f"No published image for {self.role} {self.hec_ras_version}")
        return reference

    @property
    def digest(self) -> str:
        return self.reference.rsplit("@sha256:", 1)[1]

    @property
    def pull_source(self) -> str:
        """Apptainer source: the published SIF when available, else the OCI image."""
        return self.sif if self.sif else f"docker://{self.reference}"

    @property
    def cache_name(self) -> str:
        source = self.sif.rsplit("@sha256:", 1)[1] if self.sif else self.digest
        return f"hec-ras-{self.role}_{self.hec_ras_version}-{source[:12]}.sif"


@dataclass(frozen=True)
class ResolvedSif:
    """A SIF ready for a site configuration: path, verified hash and origin."""

    path: Path
    sha256: str
    source: str  # "explicit" | "cache" | "pulled"
    image: Optional[ContainerImage] = None

    @property
    def container_identity(self) -> str:
        return f"sif:sha256:{self.sha256}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_catalog() -> list[ContainerImage]:
    payload = json.loads(
        files("ras_commander").joinpath("resources/container_images.json").read_text(encoding="utf-8")
    )
    if payload.get("schema") != CATALOG_SCHEMA:
        raise ValueError("Unsupported container image catalog schema")
    images = []
    for entry in payload["images"]:
        image = ContainerImage(
            role=entry["role"], hec_ras_version=normalize_version(entry["hec_ras_version"]),
            ghcr=entry.get("ghcr"), mirror=entry.get("mirror"),
            sif=entry.get("sif"), sif_sha256=entry.get("sif_sha256"),
        )
        if image.role not in ROLES:
            raise ValueError(f"Unknown catalog role {image.role!r}")
        for reference in (image.ghcr, image.mirror):
            if reference is not None and not _DIGEST_REFERENCE.fullmatch(reference):
                raise ValueError(f"Catalog reference must be digest-pinned: {reference}")
        if image.sif is not None and not (
                image.sif.startswith("oras://") and _DIGEST_REFERENCE.fullmatch(image.sif[7:])
                and image.sif_sha256 and _SHA256.fullmatch(image.sif_sha256)):
            raise ValueError(f"Catalog SIF must be a digest-pinned oras:// reference with sif_sha256: {image.sif}")
        images.append(image)
    return images


class RasContainerImages:
    """Static namespace for the image catalog and the local SIF cache."""

    normalize_version = staticmethod(normalize_version)
    applicable_roles = staticmethod(applicable_roles)

    @staticmethod
    def catalog() -> tuple[ContainerImage, ...]:
        """Return every published image in the packaged catalog."""
        return tuple(_load_catalog())

    @staticmethod
    def get(role: str, version: Union[str, float, int]) -> ContainerImage:
        """Return the published image for a role and release.

        Raises:
            ValueError: If the role does not apply to that release.
            LookupError: If it applies but no image has been published; build
                one (``containers/``) and pass it as ``sif_path``.
        """
        folder = normalize_version(version)
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if role not in applicable_roles(folder):
            raise ValueError(
                f"{role} does not apply to HEC-RAS {folder}: it has no HEC Linux engine; "
                "use the wine-executor role (full Windows compute under Wine)"
            )
        for image in _load_catalog():
            if image.role == role and image.hec_ras_version == folder:
                return image
        raise LookupError(
            f"No published {role} image for HEC-RAS {folder}. Build one from containers/ "
            "and pass its SIF as sif_path, or place it in the image cache."
        )

    @staticmethod
    def cache_directory(cache_dir: Optional[Union[str, Path]] = None) -> Path:
        """Return the SIF cache: ``cache_dir``, ``$RAS_COMMANDER_IMAGE_CACHE``, or
        ``~/.cache/ras-commander/images``. On a cluster, point it at shared storage
        visible to compute nodes so one copy serves every job."""
        chosen = cache_dir or os.environ.get(CACHE_ENVIRONMENT) or Path.home() / ".cache/ras-commander/images"
        return Path(chosen).expanduser()

    @staticmethod
    @log_call
    def resolve_sif(
        role: str,
        version: Union[str, float, int],
        *,
        sif_path: Optional[Union[str, Path]] = None,
        expected_sha256: Optional[str] = None,
        cache_dir: Optional[Union[str, Path]] = None,
        pull: str = "missing",
        apptainer_executable: str = "apptainer",
    ) -> ResolvedSif:
        """Return a verified SIF for a role and HEC-RAS release.

        Order: ``sif_path`` (a local or site-built image, used as-is after its
        hash is computed and, when given, checked against ``expected_sha256``),
        then the cache, then a registry pull into the cache. ``pull`` is
        ``"never"`` (offline; fail if not cached), ``"missing"`` (default), or
        ``"always"`` (refresh the cached copy).

        Cached files are named by registry digest and verified on every use:
        against the catalog's ``sif_sha256`` for published SIFs, otherwise
        against the ``.sha256`` sidecar written when the file was pulled
        (``docker://`` conversions are site-specific, so their hash is
        recorded rather than predicted).

        Returns:
            ResolvedSif: ``path``, ``sha256``, ``container_identity`` for
            ``SlurmSiteConfig``/``ApptainerSiteProfile``, and its ``source``.

        Raises:
            FileNotFoundError: ``sif_path`` is missing, or ``pull="never"`` and
                no verified cached copy exists.
            ValueError: A hash does not match.
            LookupError: No published image exists for that role and release.
            RuntimeError: ``apptainer pull`` failed.
        """
        if pull not in {"never", "missing", "always"}:
            raise ValueError("pull must be 'never', 'missing' or 'always'")
        if expected_sha256 is not None and not _SHA256.fullmatch(expected_sha256):
            raise ValueError("expected_sha256 must be a lowercase SHA-256")
        folder = normalize_version(version)
        if role not in applicable_roles(folder):
            RasContainerImages.get(role, folder)  # raises the explanatory ValueError
        if sif_path is not None:
            path = Path(sif_path).expanduser()
            if path.is_symlink() or not path.is_file():
                raise FileNotFoundError(f"sif_path must be a regular file: {path}")
            digest = _sha256_file(path)
            if expected_sha256 and digest != expected_sha256:
                raise ValueError(f"{path} SHA-256 {digest} does not match {expected_sha256}")
            return ResolvedSif(path.resolve(), digest, "explicit")

        image = RasContainerImages.get(role, folder)
        cache = RasContainerImages.cache_directory(cache_dir)
        path = cache / image.cache_name
        sidecar = path.with_name(path.name + ".sha256")
        expected = expected_sha256 or image.sif_sha256
        if pull != "always" and path.is_file() and not path.is_symlink():
            recorded = sidecar.read_text(encoding="utf-8").split()[0] if sidecar.is_file() else None
            digest = _sha256_file(path)
            wanted = expected or recorded
            if wanted and digest == wanted:
                return ResolvedSif(path, digest, "cache", image)
            logger.warning("Cached %s does not match its recorded hash; ignoring it", path)
        if pull == "never":
            raise FileNotFoundError(
                f"No verified cached SIF for {role} {folder} in {cache}. Run "
                f"{shlex.join([apptainer_executable, 'pull', str(path), image.pull_source])} "
                "where the registry is reachable, or pass sif_path."
            )
        cache.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=f".{image.cache_name}.", suffix=".partial", dir=cache)
        os.close(handle)
        os.unlink(temporary)  # apptainer pull refuses to overwrite
        try:
            completed = subprocess.run(
                [apptainer_executable, "pull", temporary, image.pull_source],
                capture_output=True, text=True, check=False, shell=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(f"apptainer pull failed: {completed.stderr.strip()[-2000:]}")
            digest = _sha256_file(Path(temporary))
            if expected and digest != expected:
                raise ValueError(f"Pulled SIF SHA-256 {digest} does not match {expected}")
            Path(temporary + ".sha256").write_text(f"{digest}  {path.name}\n", encoding="utf-8")
            os.replace(temporary + ".sha256", sidecar)
            os.replace(temporary, path)
        finally:
            for leftover in (temporary, temporary + ".sha256"):
                if os.path.exists(leftover):
                    os.unlink(leftover)
        return ResolvedSif(path, digest, "pulled", image)

    @staticmethod
    def ensure_sif_command(
        role: str,
        version: Union[str, float, int],
        cache_dir: str,
        *,
        apptainer_executable: str = "apptainer",
        pull: bool = True,
        work_dir: Optional[str] = None,
    ) -> str:
        """Return a bash snippet that reuses or fills a shared cluster cache.

        Run it on a login host (for example over the site's SSH transport). It
        prints ``<sha256>  <path>`` for a verified cached SIF, pulling it first
        when absent (unless ``pull=False``). Use the printed hash in the site
        configuration. The snippet never overwrites a verified file.

        ``work_dir`` (default ``<cache_dir>/.apptainer-work``) holds Apptainer's
        build temp and layer cache unless ``APPTAINER_TMPDIR`` /
        ``APPTAINER_CACHEDIR`` are already set. Use node-local disk when the
        cache is on network storage; unpacking image layers there is slow.
        """
        image = RasContainerImages.get(role, version)
        if not cache_dir.startswith("/") or any(c in cache_dir for c in "\x00\n"):
            raise ValueError("cache_dir must be an absolute POSIX path")
        path = f"{cache_dir.rstrip('/')}/{image.cache_name}"
        expected = image.sif_sha256 or ""
        q = shlex.quote
        pull_block = (
            f'mkdir -p {q(cache_dir)} && tmp=$(mktemp -u {q(path)}.XXXXXX.partial) && '
            f'{q(apptainer_executable)} pull "$tmp" {q(image.pull_source)} && '
            'sum=$(sha256sum "$tmp" | cut -d" " -f1) && '
            f'{{ [ -z {q(expected)} ] || [ "$sum" = {q(expected)} ] || {{ rm -f "$tmp"; echo "hash mismatch" >&2; exit 5; }}; }} && '
            f'printf "%s  %s\\n" "$sum" {q(image.cache_name)} > "$tmp.sha256" && '
            f'mv -f "$tmp.sha256" {q(path + ".sha256")} && mv -f "$tmp" {q(path)} '
            '|| { rm -f "$tmp" "$tmp.sha256"; echo "apptainer pull failed" >&2; exit 3; }'
        ) if pull else f'echo "not cached: {path}" >&2; exit 4'
        work = (work_dir or f"{cache_dir.rstrip('/')}/.apptainer-work").rstrip("/")
        if not work.startswith("/") and not work.startswith("$"):
            raise ValueError("work_dir must be an absolute POSIX path")
        return (
            "set -eu; "
            # Build in the cache filesystem unless the site chose otherwise; a
            # login host's small root can fill during SIF assembly.
            f'export APPTAINER_TMPDIR="${{APPTAINER_TMPDIR:-{work}/tmp}}" '
            f'APPTAINER_CACHEDIR="${{APPTAINER_CACHEDIR:-{work}/cache}}"; '
            'mkdir -p "$APPTAINER_TMPDIR" "$APPTAINER_CACHEDIR"; '
            'trap \'rm -rf "$APPTAINER_TMPDIR"\' EXIT; '
            f'if [ -f {q(path)} ] && [ -f {q(path + ".sha256")} ] && '
            f'[ "$(sha256sum {q(path)} | cut -d" " -f1)" = "$(cut -d" " -f1 {q(path + ".sha256")})" ]'
            f'{" && [ \"$(cut -d\" \" -f1 " + q(path + ".sha256") + ")\" = " + q(expected) + " ]" if expected else ""}; '
            f"then :; else {pull_block}; fi; "
            f'[ -f {q(path)} ] && [ -s {q(path + ".sha256")} ] || {{ echo "no verified SIF at {path}" >&2; exit 3; }}; '
            f'printf "%s  %s\\n" "$(cut -d" " -f1 {q(path + ".sha256")})" {q(path)}'
        )
