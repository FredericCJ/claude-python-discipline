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

runtime_uid=$(id -u)
runtime_gid=$(id -g)
workspace_volume=
staging_container=
report_container=
workspace_token="v5-$$"

container_is_owned() {
    [ "$("$docker_command" inspect --format \
        '{{ index .Config.Labels "python-discipline.workspace-token" }}' \
        "$1" 2>/dev/null || :)" = "$workspace_token" ]
}

volume_is_owned() {
    [ "$("$docker_command" volume inspect --format \
        '{{ index .Labels "python-discipline.workspace-token" }}' \
        "$1" 2>/dev/null || :)" = "$workspace_token" ]
}

cleanup_workspace() {
    for owned_container in "$report_container" "$staging_container"; do
        if [ -n "$owned_container" ]; then
            if ! container_is_owned "$owned_container"; then
                echo "Refusing to remove an unowned staging container." >&2
                return 1
            fi
            "$docker_command" rm --force "$owned_container" >/dev/null
        fi
    done
    if [ -n "$workspace_volume" ]; then
        if ! volume_is_owned "$workspace_volume"; then
            echo "Refusing to remove an unowned staging volume." >&2
            return 1
        fi
        "$docker_command" volume rm "$workspace_volume" >/dev/null
    fi
}
trap cleanup_workspace EXIT HUP INT TERM

case $docker_command in
    *.exe)
        mounted_repository=$(wslpath -w "$repository_root")
        copy_source="${mounted_repository}\\."
        report_destination=$(wslpath -w \
            "$repository_root/build/project-gate-docker.json")
        ;;
    *)
        mounted_repository=$repository_root
        copy_source="$repository_root/."
        report_destination="$repository_root/build/project-gate-docker.json"
        ;;
esac

# Docker Desktop projects reached through /mnt/<drive> expose every regular file
# as executable and make metadata-heavy checks dramatically slower. For the
# read-only default gate, copy exact bytes into an owned Docker volume, normalize
# Python executable intent from shebangs, and run the non-root verifier there.
# Explicit commands and shells still mount the real checkout so edits persist.
case $repository_root:$default_gate in
    /mnt/[A-Za-z]/*:true)
        workspace_volume=$("$docker_command" volume create \
            --label "python-discipline.workspace-token=$workspace_token")
        case $workspace_volume in
            ""|*[!A-Za-z0-9_.-]*)
                echo "Docker returned an unsafe staging-volume identity." >&2
                exit 1
                ;;
        esac
        staging_container=$("$docker_command" create \
            --label "python-discipline.workspace-token=$workspace_token" \
            --volume "${workspace_volume}:/workspace" \
            --workdir /workspace \
            "$image" sh -c '
                find /workspace -type f -name "*.py" -exec chmod 0644 {} +
                find /workspace -type f -name "*.py" -exec sh -c '\''
                    for python_file do
                        first_line=
                        IFS= read -r first_line < "$python_file" || :
                        case $first_line in
                            "#!"*) chmod 0755 "$python_file" ;;
                        esac
                    done
                '\'' sh {} +
                if [ "$3" = true ]; then
                    rm -f -- /workspace/build/project-gate-docker.json
                fi
                chown -R "$1:$2" /workspace
            ' sh "$runtime_uid" "$runtime_gid" "$packaged")
        if ! container_is_owned "$staging_container"; then
            echo "Docker returned an unowned staging container." >&2
            exit 1
        fi
        "$docker_command" cp --archive "$copy_source" \
            "${staging_container}:/workspace"
        "$docker_command" start --attach "$staging_container"
        "$docker_command" rm "$staging_container" >/dev/null
        staging_container=
        mounted_repository=$workspace_volume
        ;;
esac

run_container() {
    if [ -t 0 ] && [ -t 1 ]; then
        "$docker_command" run --rm --init --interactive --tty \
            --user "$runtime_uid:$runtime_gid" \
            --volume "${mounted_repository}:/workspace" \
            --workdir /workspace \
            "$image" "$@"
    else
        "$docker_command" run --rm --init \
            --user "$runtime_uid:$runtime_gid" \
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
        && [ -n "$workspace_volume" ]; then
    report_container=$("$docker_command" create \
        --label "python-discipline.workspace-token=$workspace_token" \
        --volume "${workspace_volume}:/workspace" "$image" true)
    if ! container_is_owned "$report_container"; then
        echo "Docker returned an unowned report container." >&2
        exit 1
    fi
    set +e
    "$docker_command" cp \
        "${report_container}:/workspace/build/project-gate-docker.json" \
        "$report_destination"
    report_status=$?
    set -e
    "$docker_command" rm "$report_container" >/dev/null
    report_container=
    if [ "$run_status" -eq 0 ] && [ "$report_status" -ne 0 ]; then
        echo "The successful packaged gate did not publish its JSON report." >&2
        run_status=1
    fi
fi

exit "$run_status"
