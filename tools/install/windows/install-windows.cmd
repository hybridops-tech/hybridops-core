@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem purpose: Install HybridOps.Core into Ubuntu 24.04 on Windows WSL2.
rem maintainer: HybridOps.Tech

set "DISTRO=Ubuntu-24.04"
set "PAYLOAD_DIR=%~dp0payload"
set "FORCE=false"
if /I "%~1"=="--force" set "FORCE=true"
if /I "%~1"=="/force" set "FORCE=true"

echo.
echo HybridOps.Core for Windows
echo --------------------------
echo HybridOps runs inside Ubuntu 24.04 on Windows Subsystem for Linux 2.
echo This bootstrap prepares that environment, verifies the release package,
echo and starts the HybridOps.Core installer.
echo No Windows component will be changed without your confirmation.
echo.
echo [1/4] Checking Windows prerequisites...

where wsl.exe >nul 2>&1
if errorlevel 1 (
  echo WSL is not available.
  echo Open Terminal as Administrator and run: wsl --install -d %DISTRO%
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)

wsl.exe --status >nul 2>&1
if errorlevel 1 (
  echo.
  echo Windows Subsystem for Linux needs to be installed.
  echo This is a one-time Windows setup for WSL2 and Ubuntu 24.04.
  echo Windows may require a restart before HybridOps installation can continue.
  echo.
  set "CONFIRM="
  set /p "CONFIRM=Install WSL2 and %DISTRO% now? [y/N]: "
  if /I not "!CONFIRM!"=="y" (
    echo Installation cancelled. No Windows components were changed.
    echo Press any key to close this window.
    pause >nul
    exit /b 0
  )
  fltmc >nul 2>&1
  if not errorlevel 1 (
    echo Installing WSL in this administrator window...
    wsl.exe --install -d %DISTRO% --no-launch
  ) else (
    echo Windows will request administrator approval once.
    powershell.exe -NoProfile -Command "$process = Start-Process -FilePath 'wsl.exe' -Verb RunAs -Wait -PassThru -ArgumentList '--install','-d','%DISTRO%','--no-launch'; exit $process.ExitCode"
  )
  if errorlevel 1 (
    echo WSL installation was cancelled or failed.
    echo Press any key to close this window.
    pause >nul
    exit /b 2
  )
  echo WSL setup finished.
  set "RESTART_NOW="
  set /p "RESTART_NOW=Restart Windows now to complete WSL setup? [y/N]: "
  if /I "!RESTART_NOW!"=="y" (
    echo Windows will restart in 15 seconds. Save any open work.
    shutdown.exe /r /t 15 /c "Complete Windows Subsystem for Linux setup"
    if errorlevel 1 (
      echo Windows could not schedule the restart. Restart manually before continuing.
      echo Press any key to close this window.
      pause >nul
      exit /b 2
    )
    exit /b 10
  )
  echo Restart Windows later, then run Install HybridOps.cmd again.
  echo Press any key to close this window.
  pause >nul
  exit /b 10
)

set "ARCHIVE=%PAYLOAD_DIR%\hybridops-core.tar.gz"
if not exist "%ARCHIVE%" (
  echo The HybridOps.Core installation payload is missing.
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)

set "HELPER=%PAYLOAD_DIR%\install-wsl.sh"
if not exist "%HELPER%" (
  echo The HybridOps.Core WSL installation helper is missing.
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)

echo.
echo [2/4] Checking Ubuntu 24.04...
powershell.exe -NoProfile -Command "$names = @(wsl.exe --list --quiet) | ForEach-Object { ($_ -replace [char]0, '').Trim() }; if ($names -contains '%DISTRO%') { exit 0 } else { exit 1 }"
if errorlevel 1 (
  echo.
  echo %DISTRO% is not installed.
  echo HybridOps uses this Linux environment on Windows.
  echo.
  echo Ubuntu will ask you to create a Linux username and password.
  echo Setup returns to this installer after the account is created.
  echo.
  set "CONFIRM="
  set /p "CONFIRM=Install %DISTRO% on WSL2 now? [y/N]: "
  if /I not "!CONFIRM!"=="y" (
    echo Installation cancelled. No distribution was installed.
    echo Press any key to close this window.
    pause >nul
    exit /b 0
  )
  fltmc >nul 2>&1
  if not errorlevel 1 (
    echo Installing %DISTRO% in this administrator window...
    wsl.exe --install -d %DISTRO% --no-launch
  ) else (
    powershell.exe -NoProfile -Command "$process = Start-Process -FilePath 'wsl.exe' -Verb RunAs -Wait -PassThru -ArgumentList '--install','-d','%DISTRO%','--no-launch'; exit $process.ExitCode"
  )
  if errorlevel 1 (
    echo %DISTRO% installation was cancelled or failed.
    echo Press any key to close this window.
    pause >nul
    exit /b 2
  )
  powershell.exe -NoProfile -Command "$names = @(wsl.exe --list --quiet) | ForEach-Object { ($_ -replace [char]0, '').Trim() }; if ($names -contains '%DISTRO%') { exit 0 } else { exit 1 }"
  if errorlevel 1 (
    echo %DISTRO% did not register successfully.
    echo Restart Windows, then run Install HybridOps.cmd again.
    echo Press any key to close this window.
    pause >nul
    exit /b 2
  )
  echo %DISTRO% is installed.
)

echo Provisioning %DISTRO%...
echo Create the Ubuntu username and password when prompted.
start "Ubuntu 24.04 account setup" wsl.exe -d %DISTRO%
if errorlevel 1 (
  echo %DISTRO% is installed but could not be started.
  echo Open %DISTRO% from the Start menu and complete its username prompt.
  echo Then run Install HybridOps.cmd again.
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)

set "WSL_USER="
set /a "ACCOUNT_WAIT=0"
timeout /t 1 /nobreak >nul
:wait_for_ubuntu_user
for /f "tokens=1 delims=:" %%U in ('wsl.exe -d %DISTRO% -u root -- getent passwd 1000 2^>nul') do set "WSL_USER=%%U"
if defined WSL_USER goto ubuntu_user_ready
set /a "ACCOUNT_WAIT+=1"
if !ACCOUNT_WAIT! GEQ 600 goto ubuntu_user_timeout
timeout /t 1 /nobreak >nul
goto wait_for_ubuntu_user

:ubuntu_user_timeout
echo Ubuntu account setup did not complete within 10 minutes.
echo Complete the username prompt, then run this installer again.
echo Press any key to close this window.
pause >nul
exit /b 2

:ubuntu_user_ready
if not defined WSL_USER (
  echo Unable to identify the Ubuntu user account.
  echo Open %DISTRO% once, complete its username prompt, then run this installer again.
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)
if /I "!WSL_USER!"=="root" (
  echo Ubuntu returned an invalid default user.
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)

echo Ubuntu account created. Finalizing WSL setup...
wsl.exe --terminate %DISTRO% >nul 2>&1
echo Starting Ubuntu as !WSL_USER!...
set "WSL_UID="
for /f "delims=" %%U in ('wsl.exe -d %DISTRO% -u !WSL_USER! -- id -u') do set "WSL_UID=%%U"
if not "!WSL_UID!"=="1000" (
  echo Ubuntu user validation failed for !WSL_USER! ^(uid=!WSL_UID!^).
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)
echo Ubuntu user: !WSL_USER!

echo.
echo Checking that Ubuntu is using WSL2...
wsl.exe -d %DISTRO% -- bash -lc "grep -qi microsoft-standard-wsl2 /proc/sys/kernel/osrelease"
if errorlevel 1 (
  set "CONFIRM="
  set /p "CONFIRM=Convert %DISTRO% to WSL2 now? [y/N]: "
  if /I not "!CONFIRM!"=="y" (
    echo Installation cancelled. The distribution was not converted.
    echo Press any key to close this window.
    pause >nul
    exit /b 0
  )
  echo Converting %DISTRO% to WSL2...
  wsl.exe --set-version %DISTRO% 2
  if errorlevel 1 (
    echo WSL2 conversion failed.
    echo Press any key to close this window.
    pause >nul
    exit /b 2
  )
)

echo.
echo [3/4] Verifying and preparing the release package...
for /f "usebackq delims=" %%P in (`wsl.exe -d %DISTRO% -u !WSL_USER! -- wslpath -u "%ARCHIVE%"`) do set "WSL_ARCHIVE=%%P"
if not defined WSL_ARCHIVE (
  echo Unable to map the release archive into %DISTRO%.
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)
if not "!WSL_ARCHIVE:~0,1!"=="/" (
  echo Invalid WSL archive path: !WSL_ARCHIVE!
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)

for /f "usebackq delims=" %%P in (`wsl.exe -d %DISTRO% -u !WSL_USER! -- wslpath -u "%HELPER%"`) do set "WSL_HELPER=%%P"
if not defined WSL_HELPER (
  echo Unable to map the WSL installer helper into %DISTRO%.
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)
if not "!WSL_HELPER:~0,1!"=="/" (
  echo Invalid WSL helper path: !WSL_HELPER!
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)

echo.
echo [4/4] Installing HybridOps.Core in %DISTRO%...
wsl.exe -d %DISTRO% -u !WSL_USER! -- bash "%WSL_HELPER%" "%WSL_ARCHIVE%" "%FORCE%"
if errorlevel 1 (
  echo HybridOps.Core installation failed.
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)

wsl.exe -d %DISTRO% -u !WSL_USER! -- bash -lc "command -v hyops >/dev/null 2>&1 && hyops --help >/dev/null 2>&1"
if errorlevel 1 (
  echo HybridOps.Core did not pass its final command check.
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)

echo.
set "CREATE_SHORTCUT="
set "SHORTCUT_CREATED=false"
set /p "CREATE_SHORTCUT=Create a HybridOps.Core desktop shortcut? [y/N]: "
if /I "!CREATE_SHORTCUT!"=="y" (
  powershell.exe -NoProfile -Command "$iconDir = Join-Path $env:LOCALAPPDATA 'HybridOps'; New-Item -ItemType Directory -Force -Path $iconDir | Out-Null; $iconPath = Join-Path $iconDir 'hybridops.ico'; Copy-Item -Force -LiteralPath '%PAYLOAD_DIR%\hybridops.ico' -Destination $iconPath; $shell = New-Object -ComObject WScript.Shell; $shortcut = $shell.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\HybridOps.Core.lnk'); $shortcut.TargetPath = $env:SystemRoot + '\System32\wsl.exe'; $shortcut.Arguments = '-d %DISTRO% --cd ~'; $shortcut.WorkingDirectory = $env:USERPROFILE; $shortcut.IconLocation = $iconPath + ',0'; $shortcut.Description = 'Open HybridOps.Core in Ubuntu'; $shortcut.Save()"
  if errorlevel 1 (
    echo WARN: unable to create the HybridOps.Core desktop shortcut.
  ) else (
    set "SHORTCUT_CREATED=true"
    echo Desktop shortcut created: HybridOps.Core
  )
)

echo.
echo HybridOps.Core installation completed.
if "!SHORTCUT_CREATED!"=="true" (
  echo Open HybridOps.Core from the desktop shortcut, then run: hyops --help
) else (
  echo Open Ubuntu 24.04 from the Windows Start menu, then run: hyops --help
)
echo Press any key to close this window.
pause >nul
exit /b 0
