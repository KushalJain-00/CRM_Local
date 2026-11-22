param(
    [string]$Installer = "dist\CRM_Local-Setup.exe"
)

$ErrorActionPreference = "Stop"
$installerPath = (Resolve-Path $Installer).Path
$existing = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue |
    Where-Object DisplayName -eq "CRM Local"
if ($existing) { throw "Run the installer smoke check from a clean Windows user account." }
$root = Join-Path ([IO.Path]::GetTempPath()) ("crm-smoke-" + [guid]::NewGuid())
$program = Join-Path $root "app"
$originalAppData = $env:APPDATA
$originalPort = $env:PORT
$originalMigrations = $env:CRM_APPLY_MIGRATIONS
$process = $null

function Start-Crm {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try {
        $env:PORT = [string]$listener.LocalEndpoint.Port
    } finally {
        $listener.Stop()
    }
    $script:base = "http://127.0.0.1:$env:PORT"
    $script:process = Start-Process (Join-Path $program "CRM_Local.exe") -PassThru
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if ($script:process.HasExited) {
            throw "Installed CRM exited before opening its local server (code $($script:process.ExitCode))."
        }
        try {
            if ((Invoke-RestMethod "$base/api/health" -TimeoutSec 2).ok) { return }
        } catch {
            Start-Sleep -Milliseconds 400
        }
    }
    throw "Installed CRM did not serve its health endpoint within 60 seconds."
}

function Stop-Crm {
    if ($script:process -and -not $script:process.HasExited) {
        # PyInstaller runs a parent bootloader plus the application process.
        & taskkill.exe /PID $script:process.Id /T /F | Out-Null
        $script:process.WaitForExit()
    }
    $script:process = $null
}

try {
    New-Item -ItemType Directory -Path $root | Out-Null
    $env:APPDATA = Join-Path $root "profile"
    Remove-Item Env:\CRM_APPLY_MIGRATIONS -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $env:APPDATA | Out-Null

    $setup = Start-Process $installerPath -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
        ('/DIR="{0}"' -f $program), ('/LOG="{0}"' -f (Join-Path $root "setup.log"))
    ) -PassThru -Wait
    if ($setup.ExitCode -ne 0) {
        Get-Content (Join-Path $root "setup.log") -Tail 40 -ErrorAction SilentlyContinue
        throw "Installer exited with code $($setup.ExitCode)."
    }

    Start-Crm
    if ((Invoke-WebRequest "$base/").Content -notmatch "CRM Local") { throw "Missing application shell." }
    if ((Invoke-WebRequest "$base/static/app.js").StatusCode -ne 200) { throw "Missing packaged JS." }
    if ((Invoke-RestMethod "$base/api/settings").mode -ne "local_only") { throw "Fresh profile must default to offline extraction." }

    $file = Join-Path $root "smoke.eml"
    @(
        "From: Audit Contact <audit@example.com>",
        "To: review@example.com",
        "Cc: team@example.com",
        "Bcc: archive@example.com",
        "Subject: Offline installer smoke check",
        "",
        "Regards,",
        "Audit Contact"
    ) | Set-Content -Path $file -Encoding ascii

    $import = & curl.exe --fail --silent --show-error --max-time 30 -F "files=@$file" "$base/api/intake"
    if ($LASTEXITCODE -ne 0) { throw "Offline intake request failed." }
    $result = $import | ConvertFrom-Json
    if ($result.results[0].status -ne "OK") { throw "Offline EML extraction failed." }

    $staged = (Invoke-RestMethod "$base/api/staged-contacts").rows[0]
    $approval = Invoke-RestMethod "$base/api/staged-contacts/$($staged.id)/approve" -Method Post
    if ($approval.approved -ne 1) { throw "Staged contact was not approved." }
    $contact = (Invoke-RestMethod "$base/api/contacts").rows[0]
    $details = Invoke-RestMethod "$base/api/contacts/$($contact.id)"
    if ($details.email_primary -ne "audit@example.com" -or
        $details.email_sources[0].to_emails -notmatch "review@example.com" -or
        $details.email_sources[0].cc_emails -notmatch "team@example.com" -or
        $details.email_sources[0].bcc_emails -notmatch "archive@example.com") {
        throw "The approved contact or its email provenance is incomplete."
    }
    $export = Join-Path $root "contacts.xlsx"
    Invoke-WebRequest "$base/api/contacts/export" -OutFile $export
    if ((Get-Item $export).Length -le 0) { throw "Excel export is empty." }

    Stop-Crm
    Start-Crm
    if ((Invoke-RestMethod "$base/api/contacts/$($contact.id)").email_primary -ne "audit@example.com") {
        throw "The contact did not survive restart."
    }
    Stop-Crm

    $removed = Start-Process (Join-Path $program "unins000.exe") -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"
    ) -PassThru -Wait
    if ($removed.ExitCode -ne 0 -or (Test-Path (Join-Path $program "CRM_Local.exe"))) {
        throw "Installed application was not removed successfully."
    }
    if (-not (Test-Path (Join-Path $env:APPDATA "CRM_Local\crm.db"))) {
        throw "Uninstall removed the CRM database."
    }
    Write-Host "Windows installer smoke passed: install, launch, import, review, export, restart, uninstall."
} finally {
    Stop-Crm
    $env:APPDATA = $originalAppData
    $env:PORT = $originalPort
    $env:CRM_APPLY_MIGRATIONS = $originalMigrations
    if (Test-Path $root) { Remove-Item $root -Recurse -Force }
}
