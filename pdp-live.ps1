#!/usr/bin/env pwsh
# PDP CLI with LIVE mode enabled
param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$args
)

$env:LIVE=1
python -m pdp progress @args
