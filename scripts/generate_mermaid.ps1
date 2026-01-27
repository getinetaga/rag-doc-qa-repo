<#
Generate SVG and PNG for all .mmd files under docs/diagrams using Mermaid CLI
Requires: npm install -g @mermaid-js/mermaid-cli
#>
param()
Set-StrictMode -Version Latest
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Join-Path $scriptDir '..' | Resolve-Path -Relative
$diag = Join-Path $root 'docs/diagrams'
$out = Join-Path $root 'docs/assets/diagrams'
if (-not (Test-Path $out)) { New-Item -ItemType Directory -Path $out | Out-Null }
Get-ChildItem -Path $diag -Filter *.mmd | ForEach-Object {
  $in = $_.FullName
  $base = $_.BaseName
  Write-Host "Rendering $base"
  try {
    mmdc -i $in -o (Join-Path $out "$base.svg") -b transparent
    mmdc -i $in -o (Join-Path $out "$base.png") -b transparent
  } catch {
    Write-Warning "mmdc failed for $base: $_"
  }
}
Write-Host "Done. Output in $out"
