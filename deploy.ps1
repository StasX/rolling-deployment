$ErrorActionPreference = "Stop"

wsl.exe --cd "$PSScriptRoot" -- bash ./deploy.sh @args
exit $LASTEXITCODE
