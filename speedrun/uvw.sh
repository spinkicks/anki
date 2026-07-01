#!/usr/bin/env bash
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
#
# Wrapper: run `uv` for the Speedrun content toolchain with an OUT-OF-TREE venv.
# The venv must NOT live under repos/anki, or anki's `check:minilints` copyright
# scan flags every third-party site-packages file. This scopes
# UV_PROJECT_ENVIRONMENT to THIS toolchain only (it does not set a machine-wide
# env var, which would break other uv projects).
#
# Usage (from anywhere): bash speedrun/uvw.sh sync
#                        bash speedrun/uvw.sh run pytest tests/ -v
set -euo pipefail
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/.speedrun-content-venv}"
cd "$(dirname "$0")"
exec uv "$@"
