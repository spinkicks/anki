# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
#
# Wrapper: run `uv` for the Speedrun content toolchain with an OUT-OF-TREE venv.
# The venv must NOT live under repos/anki, or anki's check:minilints copyright
# scan flags every third-party site-packages file. This scopes
# UV_PROJECT_ENVIRONMENT to THIS toolchain only (not a machine-wide env var).
#
# Usage (from anywhere): pwsh speedrun/uvw.ps1 sync
#                        pwsh speedrun/uvw.ps1 run pytest tests/ -v
if (-not $env:UV_PROJECT_ENVIRONMENT) {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $env:USERPROFILE ".speedrun-content-venv"
}
Set-Location $PSScriptRoot
& uv @args
exit $LASTEXITCODE
