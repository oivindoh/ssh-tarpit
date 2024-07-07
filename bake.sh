#!/bin/bash
export DOCKER_IMG_REPO=$(git config --local remote.origin.url|sed -n 's#.*:\([^.]*\)\/.*\.git#\1#p')
export DOCKER_IMG_N=$(git config --local remote.origin.url|sed -n 's#.*/\([^.]*\)\.git#\1#p')
export DOCKER_IMG_TAG=$(git rev-parse HEAD | cut -c1-7)

echo ${DOCKER_IMG_REPO}
echo ${DOCKER_IMG_N}
echo ${DOCKER_IMG_TAG}
docker buildx bake -f bake.hcl --push
