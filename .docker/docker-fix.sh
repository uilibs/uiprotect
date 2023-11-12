#!/bin/bash

set -o errexit
set -o pipefail
set -o nounset

DOCKER_SOCK=""
if [[ -e /var/run/docker-host.sock ]]; then
    DOCKER_SOCK="/var/run/docker-host.sock"
else
    if [[ -e /var/run/docker.sock ]]; then
        DOCKER_SOCK="/var/run/docker.sock"
    fi
fi

# fix the group ID of the docker group so it can write to /var/run/docker.sock
if [[ -n "$DOCKER_SOCK" ]]; then
    DOCKER_GID=$(ls -la $DOCKER_SOCK | awk '{print $4}')
    if [[ $DOCKER_GID != 'docker' ]]; then
        sudo groupmod -g $DOCKER_GID docker
        if [[ -f '/.codespaces' ]]; then
            echo -e '\e[1;31mYou must stop and restart the Codespace to be able to access docker properly'
        else
            echo -e '\e[1;31mYou must run the `Reload Window` command for be able to access docker properly'
        fi
    fi
fi
