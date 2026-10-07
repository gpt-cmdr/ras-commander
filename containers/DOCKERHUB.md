# Docker Hub description maintenance

The six public repositories use the `rascommander` namespace:

- `hec-ras-wine-precompute_6.5`, `hec-ras-wine-precompute_6.6`, `hec-ras-wine-precompute_7.0.1`
- `hec-ras-linux-unsteady_6.5`, `hec-ras-linux-unsteady_6.6`, `hec-ras-linux-unsteady_7.0.1`

Their current descriptions retain detailed runtime, mount, API, and recreation
guidance. Preserve those details. After the corresponding documentation PR is
merged and its pages are published, an authorized operator can prepend this
navigation block to each description:

```markdown
## RAS Commander container guides

- [Choose an execution backend](https://rascommander.info/ras/user-guide/execution-backends/)
- [Docker setup and two-stage execution](https://rascommander.info/ras/user-guide/container-execution/)
- [Published images, immutable digests, sources, and qualification](https://rascommander.info/ras/user-guide/container-images/)
- [Docker Python API](https://rascommander.info/ras/api/containers/)
- [Native Slurm + Apptainer execution](https://rascommander.info/ras/user-guide/slurm-apptainer-execution/)
- [Portable Slurm execution](https://rascommander.info/ras/user-guide/slurm-portable-execution/)

Use the same HEC-RAS version for Wine preprocessing and native computation.
Published image pairs cover 6.5, 6.6, and 7.0.1 on linux/amd64. The catalog
records the exact Docker-tested payloads and conditions. Docker qualification
does not qualify those payloads through Slurm/Apptainer. DockerWorker and
portable execution require their own image contracts.
```

For historical evidence links, use the retained release record at
`https://github.com/gpt-cmdr/ras-commander/blob/49d796f39f7ba2a3c136ee8129a22457743a32f3/containers/hecras-unsteady/RELEASE-CURRENT.md`.
Pin other historical inventory/reconstruction links to their corresponding
source commit; current guides may link to `main` or the published site.

This packet updates descriptions only. It does not authorize retagging,
rebuilding, or republishing image payloads. Retain the previous descriptions,
check all six updated listings and their links, and record the description
publication date separately from image qualification. Do not publish links
to documentation routes before those routes exist on the live site.
