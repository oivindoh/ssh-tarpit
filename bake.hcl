variable "PLATFORMS" {
  default = ["linux/amd64", "linux/arm64"]
}

variable "DOCKER_IMG_N" {
  default = "ssh-tarpit"
}

variable "DOCKER_IMG_UPDATER" {
  default = "ssh-tarpit-policy-updater"
}

variable "DOCKER_IMG_TAG" {
  default = null
}

variable "DOCKER_IMG_REPO" {
  default = null
}

group "default" {
  targets = [
    "ssh-tarpit",
    "ssh-tarpit-policy-updater"
  ]
}

target "ssh-tarpit" {
  context = "."
  dockerfile = "Dockerfile"
  tags = ["${DOCKER_IMG_REPO}/${DOCKER_IMG_N}:latest", "${DOCKER_IMG_REPO}/${DOCKER_IMG_N}:${DOCKER_IMG_TAG}"]
  args = {
  }
  platforms = "${PLATFORMS}"
}

target "ssh-tarpit-policy-updater" {
  context = "."
  dockerfile = "Dockerfile-policy-updater"
  tags = ["${DOCKER_IMG_REPO}/${DOCKER_IMG_UPDATER}:latest", "${DOCKER_IMG_REPO}/${DOCKER_IMG_UPDATER}:${DOCKER_IMG_TAG}"]
  args = {
  }
  platforms = "${PLATFORMS}"
}
