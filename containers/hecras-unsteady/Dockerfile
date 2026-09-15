# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.13.15-slim-trixie@sha256:cc9dffa47c8294ba9bb795a8dfaeb7b76f2b30acade2c52a461a2999d127eb00
FROM ${PYTHON_IMAGE}

ARG HEC_RAS_VERSION=6.5
ARG RAS_COMMANDER_COMMIT=development
ARG TINI_VERSION=0.19.0-3+b7
ARG GCC_RUNTIME_VERSION=14.2.0-19
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        "tini=${TINI_VERSION}" "libgfortran5=${GCC_RUNTIME_VERSION}" "libgomp1=${GCC_RUNTIME_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/ras-commander-source
ENV CI=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY containers/hecras-unsteady/requirements.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir -r /tmp/requirements.lock
COPY setup.py pyproject.toml README.md LICENSE ./
COPY ras_commander ./ras_commander
RUN python -m pip install --no-cache-dir --no-build-isolation --no-deps '.[compute]' \
    && python -m pip check

# Only this explicit external context contains the controlled vendor runtime.
# bundle_runtime.py excludes installers, example models, outputs and other engines.
ENV HEC_RAS_VERSION=${HEC_RAS_VERSION} \
    RAS_COMMANDER_SOURCE_COMMIT=${RAS_COMMANDER_COMMIT} \
    RAS_COMMANDER_NATIVE_RUNTIME=/opt/hecras-runtime/runtime.json \
    RAS_COMMANDER_JOB_ROOT=/job \
    RAS_COMMANDER_COMPUTE_SCRATCH=/tmp
RUN --mount=type=bind,from=hecras_runtime,source=/,target=/seed,readonly \
    mkdir /opt/hecras-runtime \
    && cp -a /seed/. /opt/hecras-runtime/ \
    && python -c "from ras_commander._container_compute import _runtime; import os; _runtime(os.environ['RAS_COMMANDER_NATIVE_RUNTIME'], os.environ['HEC_RAS_VERSION'])" \
    && chmod -R a+rX /opt/hecras-runtime \
    && find /opt/hecras-runtime -type d -exec chmod a-w {} + \
    && find /opt/hecras-runtime -type f -exec chmod a-w {} + \
    && useradd --create-home --uid 1000 rasworker \
    && mkdir /job && chown rasworker:rasworker /job

LABEL org.opencontainers.image.title="HEC-RAS native Linux unsteady compute through ras-commander" \
      org.opencontainers.image.source="https://github.com/gpt-cmdr/ras-commander" \
      org.opencontainers.image.revision="${RAS_COMMANDER_COMMIT}" \
      io.ras-commander.hec-ras-version="${HEC_RAS_VERSION}"
USER rasworker
WORKDIR /job
ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "ras_commander._container_compute"]
CMD ["compute", "--help"]
