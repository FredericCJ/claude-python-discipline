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

image=${PYTHON_DISCIPLINE_IMAGE:-python-discipline-dev:v5.0.0}

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
        ;;
    *)
        build_context=$bundle_root
        dockerfile="$bundle_root/dev/Dockerfile"
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

default_gate=false
if [ "$#" -eq 0 ]; then
    default_gate=true
    if [ "$packaged" = true ]; then
        mkdir -p "$repository_root/build"
        set -- python .agent/tools/project_gate.py --root . \
            --json build/project-gate-docker.json
    else
        set -- python tools/gate.py
    fi
fi

runtime_repository=$repository_root
staged_repository=
staging_parent=

cleanup_stage() {
    case $staged_repository in
        "$staging_parent"/python-discipline-workspace.*)
            if [ -d "$staged_repository" ]; then
                rm -rf -- "$staged_repository"
            fi
            ;;
        "")
            ;;
        *)
            echo "Refusing to remove unexpected staging path: $staged_repository" >&2
            return 1
            ;;
    esac
}
trap cleanup_stage EXIT HUP INT TERM

# Docker Desktop projects reached through /mnt/<drive> expose every regular file
# as executable and make metadata-heavy checks dramatically slower. For the
# read-only default gate, project exact bytes into WSL's Linux filesystem and
# normalize Python executable intent from the only portable source-level signal:
# a shebang. Explicit commands and shells still mount the real checkout so edits
# remain visible to the developer.
case $repository_root:$default_gate in
    /mnt/[A-Za-z]/*:true)
        staging_parent=$(CDPATH= cd -- "${TMPDIR:-/tmp}" && pwd)
        staged_repository=$(mktemp -d "$staging_parent/python-discipline-workspace.XXXXXX")
        cp -a "$repository_root/." "$staged_repository/"
        find "$staged_repository" -type f -name '*.py' -exec chmod 0644 {} +
        find "$staged_repository" -type f -name '*.py' -exec sh -c '
            for python_file do
                first_line=
                IFS= read -r first_line < "$python_file" || :
                case $first_line in
                    "#!"*) chmod 0755 "$python_file" ;;
                esac
            done
        ' sh {} +
        runtime_repository=$staged_repository
        if [ "$packaged" = true ]; then
            rm -f -- "$staged_repository/build/project-gate-docker.json"
        fi
        ;;
esac

case $docker_command in
    *.exe)
        mounted_repository=$(wslpath -w "$runtime_repository")
        ;;
    *)
        mounted_repository=$runtime_repository
        ;;
esac

run_container() {
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
}

set +e
run_container "$@"
run_status=$?
set -e

if [ "$packaged" = true ] && [ "$default_gate" = true ] \
        && [ -n "$staged_repository" ] \
        && [ -f "$staged_repository/build/project-gate-docker.json" ]; then
    cp "$staged_repository/build/project-gate-docker.json" \
        "$repository_root/build/project-gate-docker.json"
fi

exit "$run_status"
