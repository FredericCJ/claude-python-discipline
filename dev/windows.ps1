[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string] $EnvironmentName = "claude",

    [Parameter()]
    [switch] $Refresh,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Command
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$condaInfo = Get-Command conda -ErrorAction SilentlyContinue
if ($null -eq $condaInfo) {
    throw "Conda is required but no conda command is available on PATH."
}
$condaCommand = if ($condaInfo.Source) { $condaInfo.Source } else { $condaInfo.Name }

$scriptDirectory = Split-Path -Parent $PSCommandPath
$bundleRoot = Split-Path -Parent $scriptDirectory
if ((Split-Path -Leaf $bundleRoot) -eq ".agent") {
    $repositoryRoot = Split-Path -Parent $bundleRoot
    $packaged = $true
} else {
    $repositoryRoot = $bundleRoot
    $packaged = $false
}

$environmentFile = Join-Path $bundleRoot "environment.yml"
$checker = Join-Path $bundleRoot "tools\check_env.py"
if (-not (Test-Path -LiteralPath $environmentFile -PathType Leaf)) {
    throw "The shipped environment declaration is missing: $environmentFile"
}
if (-not (Test-Path -LiteralPath $checker -PathType Leaf)) {
    throw "The shipped environment verifier is missing: $checker"
}

function Invoke-CondaChecked {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)

    & $script:condaCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Conda failed with exit code $LASTEXITCODE while running: $($Arguments -join ' ')"
    }
}

function Test-DeclaredEnvironment {
    & $script:condaCommand run --no-capture-output --name $EnvironmentName `
        python $checker --file $environmentFile --quiet *> $null
    return $LASTEXITCODE -eq 0
}

if ($Refresh -or -not (Test-DeclaredEnvironment)) {
    Write-Host "Creating or repairing Conda environment '$EnvironmentName' from environment.yml."
    Invoke-CondaChecked @(
        "env", "update", "--name", $EnvironmentName,
        "--file", $environmentFile, "--prune"
    )
}

# Conda's success only says its transaction completed. The independent checker
# decides whether the resulting interpreter and every declared tool really match.
Invoke-CondaChecked @(
    "run", "--no-capture-output", "--name", $EnvironmentName,
    "python", $checker, "--file", $environmentFile
)

if (@($Command).Count -eq 0) {
    if ($packaged) {
        $buildDirectory = Join-Path $repositoryRoot "build"
        New-Item -ItemType Directory -Path $buildDirectory -Force | Out-Null
        $Command = @(
            "python", ".agent\tools\project_gate.py", "--root", ".",
            "--json", "build\project-gate-windows.json"
        )
    } else {
        $Command = @("python", "tools\gate.py")
    }
}

Push-Location $repositoryRoot
try {
    & $condaCommand run --no-capture-output --name $EnvironmentName @Command
    $commandExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $commandExit
