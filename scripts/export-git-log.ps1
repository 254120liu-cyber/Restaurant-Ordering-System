$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
git --no-pager log --all --graph --date=iso-strict --pretty=format:'%h %ad %an <%ae> %d %s' | Out-File -Encoding utf8 git-log.txt
Write-Host '已导出真实Git提交历史'
