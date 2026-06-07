#!/usr/bin/env pwsh
# PDP CLI Wrapper for PowerShell
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
python -m pdp @args
