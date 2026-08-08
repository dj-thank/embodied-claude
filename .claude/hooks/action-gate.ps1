param(
    [string]$ActionPolicyDirectory = ""
)

$ErrorActionPreference = "Stop"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

if ([string]::IsNullOrWhiteSpace($ActionPolicyDirectory) -and $env:CLAUDE_PROJECT_DIR) {
    $ActionPolicyDirectory = Join-Path $env:CLAUDE_PROJECT_DIR "action-policy"
}

if (
    [string]::IsNullOrWhiteSpace($ActionPolicyDirectory) -or
    -not (Test-Path -LiteralPath $ActionPolicyDirectory -PathType Container)
) {
    [Console]::Error.WriteLine("action gate project directory is unavailable")
    exit 2
}

$uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue
if ($null -eq $uv) {
    [Console]::Error.WriteLine("action gate runtime is unavailable")
    exit 2
}

try {
    $rawInput = [Console]::In.ReadToEnd()
    $output = $rawInput | & $uv.Source run --locked --no-sync `
        --directory $ActionPolicyDirectory embodied-action-gate 2>$null
    $gateExitCode = $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine("action gate evaluation failed")
    exit 2
}

if ($gateExitCode -ne 0) {
    [Console]::Error.WriteLine("action gate evaluation failed")
    exit 2
}

$decision = $output -join [Environment]::NewLine
if (-not $decision.StartsWith('{"hookSpecificOutput":', [StringComparison]::Ordinal)) {
    [Console]::Error.WriteLine("action gate returned an invalid decision")
    exit 2
}

[Console]::Out.WriteLine($decision)
exit 0
