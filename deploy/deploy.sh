#!/usr/bin/env bash

set -Eeuo pipefail

[[ "$(id -un)" == "model-platform" ]] || {
  echo "ERROR: run this script as model-platform" >&2
  exit 1
}

SOURCE_DIR="${MODEL_PLATFORM_SOURCE_DIR:-/data/jiaqimeng/projects/Tuojing_model_platform_service}"
APP_DIR="${MODEL_PLATFORM_APP_DIR:-/data/model-platform/Tuojing_model_platform_service}"
USER_UNIT_DIR="${HOME}/.config/systemd/user"
EXPECTED_BRANCH="master"

for command_name in git install rsync sed systemctl; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
done

[[ -d "${SOURCE_DIR}/.git" ]] || {
  echo "ERROR: source is not a Git repository: ${SOURCE_DIR}" >&2
  exit 1
}

git_source=(git -c "safe.directory=${SOURCE_DIR}" -C "${SOURCE_DIR}")
branch="$("${git_source[@]}" branch --show-current)"
[[ "${branch}" == "${EXPECTED_BRANCH}" ]] || {
  echo "ERROR: source branch must be ${EXPECTED_BRANCH}; current branch is ${branch}" >&2
  exit 1
}

[[ -z "$("${git_source[@]}" status --porcelain)" ]] || {
  echo "ERROR: source repository has uncommitted or untracked files" >&2
  "${git_source[@]}" status --short >&2
  exit 1
}

source_commit="$("${git_source[@]}" rev-parse HEAD)"
origin_commit="$("${git_source[@]}" rev-parse --verify "origin/${EXPECTED_BRANCH}")"
[[ "${source_commit}" == "${origin_commit}" ]] || {
  echo "ERROR: local ${EXPECTED_BRANCH} does not match origin/${EXPECTED_BRANCH}" >&2
  echo "Run git pull --ff-only origin ${EXPECTED_BRANCH} as jiaqimeng first." >&2
  exit 1
}

[[ -x "${SOURCE_DIR}/.venv/bin/tuojing-model-api" ]] || {
  echo "ERROR: source virtual environment is missing the API command" >&2
  exit 1
}
[[ -x "${SOURCE_DIR}/.venv/bin/tuojing-model-ui" ]] || {
  echo "ERROR: source virtual environment is missing the UI command" >&2
  exit 1
}

install -d -m 0750 "${APP_DIR}"
rsync -a --no-owner --no-group --delete \
  --exclude='.git/' \
  --exclude='.runtime/' \
  --exclude='dist/' \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  "${SOURCE_DIR}/" \
  "${APP_DIR}/"

# The copied virtual environment contains absolute references to SOURCE_DIR.
# Rewrite this project's entry points and editable source link for APP_DIR.
for entry_point in tuojing-model-api tuojing-model-ui; do
  sed -i "1c #!${APP_DIR}/.venv/bin/python3" \
    "${APP_DIR}/.venv/bin/${entry_point}"
done

site_packages="$(
  "${APP_DIR}/.venv/bin/python3" -c \
    'import sysconfig; print(sysconfig.get_paths()["purelib"])'
)"
printf '%s\n' "${APP_DIR}/src" \
  >"${site_packages}/tuojing_model_platform_service.pth"

installed_module="$(
  "${APP_DIR}/.venv/bin/python3" -c \
    'import pathlib, tuojing_model_platform_service as package; print(pathlib.Path(package.__file__).resolve())'
)"
[[ "${installed_module}" == "${APP_DIR}/src/"* ]] || {
  echo "ERROR: deployed Python package points outside release directory: ${installed_module}" >&2
  exit 1
}

install -d -m 0750 "${USER_UNIT_DIR}"
install -m 0644 \
  "${APP_DIR}/deploy/systemd/tuojing-model-api.service" \
  "${APP_DIR}/deploy/systemd/tuojing-model-ui.service" \
  "${USER_UNIT_DIR}/"

systemctl --user daemon-reload
systemctl --user enable tuojing-model-api.service tuojing-model-ui.service >/dev/null
systemctl --user restart tuojing-model-api.service
systemctl --user restart tuojing-model-ui.service

echo "MODEL_PLATFORM_DEPLOY=PASS"
echo "SOURCE_COMMIT=${source_commit}"
