#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
bundle_root=$(dirname -- "$script_dir")
if [ "$(basename -- "$bundle_root")" = ".agent" ]; then
    repository_root=$(dirname -- "$bundle_root")
    packaged=true
else
    repository_root=$bundle_root
    packaged=false
fi

image=${PYTHON_DISCIPLINE_IMAGE:-python-discipline-dev:v4.1.0}

# WSL distributions do not all expose Docker Desktop's Linux shim. Its Windows
# CLI is still callable from WSL, so support that normal Windows 11 topology
# without asking the developer to install a second Docker client.
if [ -n "${DOCKER:-}" ]; then
    docker_command=$DOCKER
elif command -v docker >/dev/null 2>&1 \
        && docker version >/dev/null 2>&1; then
    docker_command=$(command -v docker)
elif [ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]; then
    docker_command="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
else
    echo "Docker is required but no docker command is available." >&2
    exit 127
fi

case $docker_command in
    *.exe)
        if ! command -v wslpath >/dev/null 2>&1; then
            echo "A Windows Docker executable requires wslpath." >&2
            exit 127
        fi
        build_context=$(wslpath -w "$bundle_root")
        dockerfile="${build_context}\\dev\\Dockerfile"
        mounted_repository=$(wslpath -w "$repository_root")
        ;;
    *)
        build_context=$bundle_root
        dockerfile="$bundle_root/dev/Dockerfile"
        mounted_repository=$repository_root
        ;;
esac

build_image() {
    "$docker_command" build \
        --tag "$image" \
        --file "$dockerfile" \
        "$build_context"
}

mode=${1:-run}
if [ "$#" -gt 0 ]; then
    shift
fi

case $mode in
    build)
        if [ "$#" -ne 0 ]; then
            echo "usage: dev/docker.sh build" >&2
            exit 2
        fi
        build_image
        exit 0
        ;;
    run)
        ;;
    shell)
        set -- bash
        ;;
    *)
        set -- "$mode" "$@"
        ;;
esac

build_image

if [ "$#" -eq 0 ]; then
    if [ "$packaged" = true ]; then
        mkdir -p "$repository_root/build"
        set -- python .agent/tools/project_gate.py --root . \
            --json build/project-gate-docker.json
    else
        set -- python tools/gate.py
    fi
fi

if [ -t 0 ] && [ -t 1 ]; then
    "$docker_command" run --rm --init --interactive --tty \
        --user "$(id -u):$(id -g)" \
        --volume "${mounted_repository}:/workspace" \
        --workdir /workspace \
        "$image" "$@"
else
    "$docker_command" run --rm --init \
        --user "$(id -u):$(id -g)" \
        --volume "${mounted_repository}:/workspace" \
        --workdir /workspace \
        "$image" "$@"
fi
