# syntax=docker/dockerfile:1@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32

# A tag makes the intended upstream release legible; the manifest-list digest
# makes it immutable on both amd64 and arm64. Updating either is a reviewed
# supply-chain change, never an incidental rebuild.
FROM condaforge/miniforge3:25.3.1-0@sha256:1e65803d646bf8503728001dddb5756f3e8235e0883c19b5a5ad1da85cff0905

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Only the shared lock, its dependency-free verifier, and the entry point enter
# the image. The application/component checkout is mounted at runtime; it is not
# captured in an image layer.
COPY environment.yml /opt/python-discipline/environment.yml
COPY tools/check_env.py /opt/python-discipline/tools/check_env.py
COPY --chmod=0555 dev/container-entrypoint.sh /usr/local/bin/python-discipline-entrypoint

# The Python Pyright launcher uses a global Node only when it is visible on
# PATH; otherwise it silently provisions another runtime through nodeenv. Put
# the declared environment first before executing any verifier and disable the
# alternative wheel strategy. The environment checker has already made Node's
# exact identity a prerequisite for reaching Pyright.
ENV PATH="/opt/conda/envs/claude/bin:/opt/conda/bin:${PATH}" \
    PYRIGHT_PYTHON_GLOBAL_NODE="true" \
    PYRIGHT_PYTHON_NODEJS_WHEEL="false"

RUN --mount=type=cache,target=/opt/conda/pkgs \
    --mount=type=cache,target=/root/.cache/pip \
    conda env create --file /opt/python-discipline/environment.yml \
    && /opt/conda/envs/claude/bin/python /opt/python-discipline/tools/check_env.py \
       --file /opt/python-discipline/environment.yml \
    && /opt/conda/envs/claude/bin/python -m pip check \
    && /opt/conda/envs/claude/bin/python -m pyright --version \
    && rm -f /opt/python-discipline/condaenv.*.requirements.txt \
    && find /opt/conda -type d -name __pycache__ -prune -exec rm -rf '{}' '+'

ENV CONDA_DEFAULT_ENV="claude" \
    CONDA_PREFIX="/opt/conda/envs/claude" \
    HOME="/tmp/python-discipline-home" \
    XDG_CACHE_HOME="/tmp/python-discipline-home/.cache" \
    XDG_CONFIG_HOME="/tmp/python-discipline-home/.config" \
    PYTHONDONTWRITEBYTECODE="1" \
    PYTHONNOUSERSITE="1"

WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/python-discipline-entrypoint"]
CMD ["python", "tools/gate.py"]
