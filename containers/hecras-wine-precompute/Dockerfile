# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.13.15-slim-trixie@sha256:cc9dffa47c8294ba9bb795a8dfaeb7b76f2b30acade2c52a461a2999d127eb00

# Build the CPU-numbering shim (see cpushim.c) without adding a compiler to the
# published image. The hecras-wine-executor build can export only the shim with
# --target cpushim-artifact --output type=local,dest=<dir>.
FROM ${PYTHON_IMAGE} AS cpushim
ARG GCC_VERSION=4:14.2.0-1
ARG LIBC6_DEV_VERSION=2.41-12+deb13u4
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        "gcc=${GCC_VERSION}" \
        "libc6-dev=${LIBC6_DEV_VERSION}" \
    && rm -rf /var/lib/apt/lists/*
COPY containers/hecras-wine-precompute/cpushim.c /src/cpushim.c
RUN mkdir /out \
    && gcc -shared -fPIC -O2 -Wall -o /out/cpushim.so /src/cpushim.c -ldl -pthread \
    && nm -D --defined-only /out/cpushim.so | grep -qw sched_getcpu

FROM scratch AS cpushim-artifact
COPY --from=cpushim /out/cpushim.so /cpushim.so

FROM ${PYTHON_IMAGE} AS base

ARG RAS_COMMANDER_COMMIT
ARG RAS_COMMANDER_WHEEL_SHA256
ARG HEC_RAS_VERSION=6.6
ARG WINE_VERSION=11.0.0.0~trixie-1
ARG XVFB_VERSION=2:21.1.16-1.3+deb13u4
ARG XAUTH_VERSION=1:1.1.2-1.1
ARG PROCPS_VERSION=2:4.0.4-9
ARG TINI_VERSION=0.19.0-3+b8

RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates=20250419 \
        gnupg=2.4.7-21+deb13u1 \
        wget=1.25.0-2 \
    && mkdir -p /etc/apt/keyrings \
    && wget -qO /etc/apt/keyrings/winehq-archive.key \
        https://dl.winehq.org/wine-builds/winehq.key \
    && wget -qO /etc/apt/sources.list.d/winehq-trixie.sources \
        https://dl.winehq.org/wine-builds/debian/dists/trixie/winehq-trixie.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        "winehq-stable=${WINE_VERSION}" \
        "xvfb=${XVFB_VERSION}" \
        "xauth=${XAUTH_VERSION}" \
        "procps=${PROCPS_VERSION}" \
        "tini=${TINI_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/hecras-prepare
RUN test -n "${RAS_COMMANDER_COMMIT}" \
    && test "${#RAS_COMMANDER_COMMIT}" -eq 40 \
    && test -n "${RAS_COMMANDER_WHEEL_SHA256}" \
    && test "${#RAS_COMMANDER_WHEEL_SHA256}" -eq 64
COPY containers/hecras-wine-precompute/prepare.py ./prepare.py
COPY containers/hecras-wine-precompute/windows_worker.py ./windows_worker.py
COPY containers/hecras-wine-precompute/model_checks.py ./model_checks.py
COPY --from=cpushim /out/cpushim.so ./cpushim.so

RUN useradd --create-home --uid 1000 rasworker \
    && mkdir -p /job /runtime/wine-seed /run/ras-job \
    && chown -R rasworker:rasworker /job /run/ras-job

# RAS_COMMANDER_WINE_CPU_SHIM is shared with the portable executor
# (ras_commander.remote.execute_request); "0" or an empty value disables it.
ENV RAS_COMMANDER_PREPARE_JOB_ROOT=/job \
    RAS_COMMANDER_PREPARE_RUNTIME_MANIFEST=/runtime/wine-seed/runtime.json \
    RAS_COMMANDER_PREPARE_SCRATCH_ROOT=/run/ras-job \
    RAS_COMMANDER_PREPARE_HECRAS_VERSION=${HEC_RAS_VERSION} \
    RAS_COMMANDER_PREPARE_RAS_COMMANDER_COMMIT=${RAS_COMMANDER_COMMIT} \
    RAS_COMMANDER_PREPARE_RAS_COMMANDER_WHEEL_SHA256=${RAS_COMMANDER_WHEEL_SHA256} \
    RAS_COMMANDER_WINE_CPU_SHIM=/opt/hecras-prepare/cpushim.so \
    WINEDEBUG=err+all,fixme-all

LABEL org.opencontainers.image.title="HEC-RAS Wine preprocessing through ras-commander" \
      org.opencontainers.image.source="https://github.com/gpt-cmdr/ras-commander" \
      io.ras-commander.hec-ras-version="${HEC_RAS_VERSION}" \
      io.ras-commander.commit="${RAS_COMMANDER_COMMIT}" \
      io.ras-commander.wheel-sha256="${RAS_COMMANDER_WHEEL_SHA256}" \
      io.ras-commander.cpu-shim="/opt/hecras-prepare/cpushim.so"

USER rasworker
ENTRYPOINT ["/usr/bin/tini", "--", "python", "/opt/hecras-prepare/prepare.py"]
CMD ["prepare", "--help"]

# Release builds provide a prepared profile as an external named build context.
# --target base remains available for development with a mounted runtime.
FROM base AS bundled
USER root
# Copy and normalize ownership in one layer to avoid duplicating the runtime.
RUN --mount=type=bind,from=hecras_runtime,target=/seed,readonly \
    cp -a /seed/runtime.json /seed/prefix /runtime/wine-seed/ \
    && chown -R root:root /runtime/wine-seed \
    && find /runtime/wine-seed -type d -exec chmod 755 {} + \
    && find /runtime/wine-seed -type f -exec chmod u+rw,go+r,go-w {} + \
    && python -c "import os; from prepare import load_runtime; load_runtime(os.environ['RAS_COMMANDER_PREPARE_RUNTIME_MANIFEST'], os.environ['RAS_COMMANDER_PREPARE_HECRAS_VERSION'])"
ENV RAS_COMMANDER_PREPARE_BUNDLED_RUNTIME=1 \
    RAS_COMMANDER_TCU_PROBE=C:\\ras-commander-runtime\\tcu-probe.json
LABEL io.ras-commander.hec-ras-runtime="bundled"
USER rasworker
