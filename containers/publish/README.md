# Publishing release images to GHCR

`publish_ghcr.py` pushes qualified release images to `ghcr.io/gpt-cmdr` and records them in
the package catalog (`ras_commander/resources/container_images.json`), which
`RasContainerImages.resolve_sif()` and `RasDocker` read.

| Input | Produced by | Pushed as |
| --- | --- | --- |
| `hec-ras-<role>_<version>_<build>.tar.gz` + `.sha256` | `hecras-wine-runtime/build_release_images.sh`, the native recipe | `ghcr.io/gpt-cmdr/hec-ras-<role>_<version>:<tag>` (OCI) → catalog `ghcr` |
| `hec-ras-<role>_<version>*.sif` + `.sha256` | `apptainer/build_sif_from_archive.sbatch` | `ghcr.io/gpt-cmdr/hec-ras-<role>-sif_<version>:<tag>` (ORAS) → catalog `sif`, `sif_sha256` |

Publish only images that passed qualification, one per role and release (the script refuses
duplicates).

1. On a host with Docker, `oras`, and read access to the staging folder, log in with a token
   that has `write:packages`: `docker login ghcr.io` and `oras login ghcr.io`.
2. Review the plan: `python containers/publish/publish_ghcr.py --archives <dir> --sifs <dir> --tag <tag>`.
3. Publish: add `--execute --confirm-terms-publication`. Wine images built here carry the HEC-RAS
   Terms and Conditions acceptance given at build time (6.1 and later); publishing them is a
   decision for the repository owner, which the flag records.
4. Make each new package public in its GHCR settings (new packages are private).
5. Commit the updated catalog. Check that `apptainer pull` of a `sif` entry reproduces its
   `sif_sha256` from a clean machine.

Use the ras-commander release the images embed as the tag (the executor and pre-compute images
contain its wheel), or a qualification tag such as `0.105.0-qual-20261014`.
