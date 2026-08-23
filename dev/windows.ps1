Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# PowerShell's parameter binder also examines tokens intended for the child
# command. In particular, Python arguments such as ``--error`` can bind to the
# shell's common ``-ErrorAction`` parameter, while ``-c`` can be rejected as an
# unknown launcher parameter. Parse only the launcher's leading options here;
# after the first command token, every remaining token belongs to that command.
$EnvironmentName = "claude"
$Refresh = $false
$Command = @()
$rawArguments = @($args)
$argumentIndex = 0
while ($argumentIndex -lt $rawArguments.Count) {
    $argument = $rawArguments[$argumentIndex]
    if ($argument -ieq "-EnvironmentName") {
        $argumentIndex += 1
        if ($argumentIndex -ge $rawArguments.Count) {
            throw "-EnvironmentName requires a non-empty value."
        }
        $EnvironmentName = $rawArguments[$argumentIndex]
        if ([string]::IsNullOrWhiteSpace($EnvironmentName)) {
            throw "-EnvironmentName requires a non-empty value."
        }
        $argumentIndex += 1
        continue
    }
    if ($argument -ieq "-Refresh") {
        $Refresh = $true
        $argumentIndex += 1
        continue
    }
    if ($argument -eq "--") {
        $argumentIndex += 1
    }
    if ($argumentIndex -lt $rawArguments.Count) {
        $Command = @($rawArguments[$argumentIndex..($rawArguments.Count - 1)])
    }
    break
}

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

    # Windows PowerShell 5.1 promotes a native program's stderr to ErrorRecord.
    # Let Conda finish, then decide from its process status rather than from the
    # stream on which it chose to print progress or diagnostics.
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $script:condaCommand @Arguments
        $condaExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedPreference
    }
    if ($condaExit -ne 0) {
        throw "Conda failed with exit code $condaExit while running: $($Arguments -join ' ')"
    }
}

function Test-DeclaredEnvironment {
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $script:condaCommand run --no-capture-output --name $EnvironmentName `
            python $checker --file $environmentFile --quiet *> $null
        $condaExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedPreference
    }
    return $condaExit -eq 0
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
