# Loads a generated dataset into a local MariaDB server.
# Usage:  .\load_mariadb.ps1 -Dataset full -User root
param(
    [string]$Dataset = "full",
    [string]$User = "root",
    [string]$Database = "ap_automation",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 3306
)
$ErrorActionPreference = "Stop"
$sqlDir = Join-Path $PSScriptRoot "..\data\$Dataset\sql"
if (-not (Test-Path "$sqlDir\seed.sql")) {
    Write-Error "No seed found at $sqlDir. Run: cd backend; python -m apflow generate --name $Dataset"
}
$client = Get-Command mariadb -ErrorAction SilentlyContinue
if (-not $client) { $client = Get-Command mysql -ErrorAction SilentlyContinue }
if (-not $client) {
    $guess = Get-ChildItem "C:\Program Files\MariaDB*\bin\mariadb.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($guess) { $client = $guess.FullName } else { Write-Error "mariadb client not found. Add MariaDB\bin to PATH." }
} else { $client = $client.Source }

$secure = Read-Host "MariaDB password for $User" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
$env:MYSQL_PWD = $plain
try {
    & $client -h $HostName -P $Port -u $User -e "CREATE DATABASE IF NOT EXISTS $Database CHARACTER SET utf8mb4;"
    Write-Host "Loading schema..."
    Get-Content "$sqlDir\schema.sql" -Raw | & $client -h $HostName -P $Port -u $User $Database
    Write-Host "Loading seed data (this can take a minute)..."
    Get-Content "$sqlDir\seed.sql" -Raw | & $client -h $HostName -P $Port -u $User $Database
    & $client -h $HostName -P $Port -u $User $Database -e "SELECT 'vendors' t, COUNT(*) n FROM vendors UNION ALL SELECT 'purchase_orders', COUNT(*) FROM purchase_orders UNION ALL SELECT 'invoices', COUNT(*) FROM invoices UNION ALL SELECT 'payments', COUNT(*) FROM payments;"
    Write-Host "Done. Database: $Database"
} finally {
    Remove-Item Env:\MYSQL_PWD -ErrorAction SilentlyContinue
}
