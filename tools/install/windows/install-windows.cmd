@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem purpose: Install HybridOps.Core into Ubuntu 24.04 on Windows WSL2.
rem maintainer: HybridOps.Tech

set "DISTRO=Ubuntu-24.04"
set "PAYLOAD_DIR=%~dp0payload"
set "HYOPS_USER_DIR=%LOCALAPPDATA%\HybridOps"
set "WSL_SETUP_MARKER=%HYOPS_USER_DIR%\wsl-setup.pending"
set "FORCE=false"
if /I "%~1"=="--force" set "FORCE=true"
if /I "%~1"=="/force" set "FORCE=true"

echo.
echo HybridOps.Core for Windows
echo --------------------------
echo This installer prepares Ubuntu 24.04 on Windows Subsystem for Linux 2,
echo verifies the release package and installs HybridOps.Core.
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
  if not exist "%HYOPS_USER_DIR%" mkdir "%HYOPS_USER_DIR%"
  >"%WSL_SETUP_MARKER%" echo pending
  fltmc >nul 2>&1
  if not errorlevel 1 (
    echo Installing WSL in this administrator window...
    wsl.exe --install -d %DISTRO% --no-launch
  ) else (
    echo Windows will request administrator approval once.
    powershell.exe -NoProfile -Command "$process = Start-Process -FilePath 'wsl.exe' -Verb RunAs -Wait -PassThru -ArgumentList '--install','-d','%DISTRO%','--no-launch'; exit $process.ExitCode"
  )
  if errorlevel 1 (
    del /q "%WSL_SETUP_MARKER%" >nul 2>&1
    echo WSL installation was cancelled or failed.
    echo Press any key to close this window.
    pause >nul
    exit /b 2
  )
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
  if not exist "%HYOPS_USER_DIR%" mkdir "%HYOPS_USER_DIR%"
  >"%WSL_SETUP_MARKER%" echo pending
  fltmc >nul 2>&1
  if not errorlevel 1 (
    echo Installing %DISTRO% in this administrator window...
    wsl.exe --install -d %DISTRO% --no-launch
  ) else (
    powershell.exe -NoProfile -Command "$process = Start-Process -FilePath 'wsl.exe' -Verb RunAs -Wait -PassThru -ArgumentList '--install','-d','%DISTRO%','--no-launch'; exit $process.ExitCode"
  )
  if errorlevel 1 (
    del /q "%WSL_SETUP_MARKER%" >nul 2>&1
    echo %DISTRO% installation was cancelled or failed.
    echo Press any key to close this window.
    pause >nul
    exit /b 2
  )
  powershell.exe -NoProfile -Command "$names = @(wsl.exe --list --quiet) | ForEach-Object { ($_ -replace [char]0, '').Trim() }; if ($names -contains '%DISTRO%') { exit 0 } else { exit 1 }"
  if errorlevel 1 (
    echo.
    echo Windows must restart before %DISTRO% can finish registration.
    set "RESTART_NOW="
    set /p "RESTART_NOW=Restart Windows now? [y/N]: "
    if /I "!RESTART_NOW!"=="y" (
      echo Windows will restart in 15 seconds. Save any open work.
      shutdown.exe /r /t 15 /c "Complete HybridOps.Core WSL setup"
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
  echo %DISTRO% is installed.
)

echo Provisioning %DISTRO%...
set "WSL_USER="
for /f "tokens=1 delims=:" %%U in ('wsl.exe -d %DISTRO% -u root -- getent passwd 1000 2^>nul') do set "WSL_USER=%%U"
if not defined WSL_USER (
  echo Create the Ubuntu account used by HybridOps.
  set "NEW_WSL_USER="
  set /p "NEW_WSL_USER=Ubuntu username: "
  set "HYOPS_NEW_WSL_USER=!NEW_WSL_USER!"
  powershell.exe -NoProfile -Command "if ($env:HYOPS_NEW_WSL_USER -cmatch '^[a-z_][a-z0-9_-]{0,31}$') { exit 0 } else { exit 1 }"
  if errorlevel 1 (
    echo Use 1 to 32 lowercase letters, numbers, underscores or hyphens.
    echo The first character must be a letter or underscore.
    echo Press any key to close this window.
    pause >nul
    exit /b 2
  )
  wsl.exe -d %DISTRO% -u root -- useradd --create-home --shell /bin/bash --uid 1000 !NEW_WSL_USER!
  if errorlevel 1 (
    echo Unable to create the Ubuntu account.
    echo Press any key to close this window.
    pause >nul
    exit /b 2
  )
  if exist "%WSL_SETUP_MARKER%" (
    powershell.exe -NoProfile -Command "Get-Process -Name 'wslsettings' -ErrorAction SilentlyContinue | ForEach-Object { [void]$_.CloseMainWindow() }"
  )
  echo Create and confirm the Ubuntu password.
  wsl.exe -d %DISTRO% -u root -- passwd !NEW_WSL_USER!
  if errorlevel 1 (
    wsl.exe -d %DISTRO% -u root -- userdel --remove !NEW_WSL_USER! >nul 2>&1
    echo Ubuntu password setup did not complete. The incomplete account was removed.
    echo Press any key to close this window.
    pause >nul
    exit /b 2
  )
  wsl.exe -d %DISTRO% -u root -- usermod --append --groups sudo !NEW_WSL_USER!
  if errorlevel 1 (
    echo Unable to grant administrative access to the Ubuntu account.
    echo Press any key to close this window.
    pause >nul
    exit /b 2
  )
  wsl.exe -d %DISTRO% -u root -- bash -lc "printf '[user]\ndefault=!NEW_WSL_USER!\n' > /etc/wsl.conf"
  if errorlevel 1 (
    echo Unable to set the default Ubuntu account.
    echo Press any key to close this window.
    pause >nul
    exit /b 2
  )
  set "WSL_USER=!NEW_WSL_USER!"
)
if /I "!WSL_USER!"=="root" (
  echo Ubuntu returned an invalid default user.
  echo Press any key to close this window.
  pause >nul
  exit /b 2
)

echo Ubuntu account ready. Finalizing WSL setup...
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

wsl.exe -d %DISTRO% -u !WSL_USER! -- bash -lc "test -e \"${HOME}/.hybridops/core\""
if not errorlevel 1 (
  echo.
  echo Existing HybridOps.Core installation found.
  echo The installed Core files will be updated.
  set "FORCE=true"
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
set "SHORTCUT_EXISTS=false"
powershell.exe -NoProfile -Command "$path = Join-Path ([Environment]::GetFolderPath('Desktop')) 'HybridOps.Core.lnk'; if (Test-Path -LiteralPath $path) { exit 0 }; exit 1"
if not errorlevel 1 (
  set "SHORTCUT_EXISTS=true"
  set "CREATE_SHORTCUT=y"
) else (
  set /p "CREATE_SHORTCUT=Create a HybridOps.Core desktop shortcut? [y/N]: "
)
if /I "!CREATE_SHORTCUT!"=="y" (
  set "LAUNCHER_DIR=%HYOPS_USER_DIR%"
  set "LAUNCHER=!LAUNCHER_DIR!\Open HybridOps.cmd"
  if not exist "!LAUNCHER_DIR!" mkdir "!LAUNCHER_DIR!"
  copy /y "%PAYLOAD_DIR%\launcher.cmd" "!LAUNCHER!" >nul
  if errorlevel 1 (
    echo WARN: unable to install the HybridOps.Core launcher.
  )
  powershell.exe -NoProfile -Command "$iconDir = Join-Path $env:LOCALAPPDATA 'HybridOps'; $iconPath = Join-Path $iconDir 'hybridops.ico'; $launcherPath = Join-Path $iconDir 'Open HybridOps.cmd'; Copy-Item -Force -LiteralPath '%PAYLOAD_DIR%\hybridops.ico' -Destination $iconPath; $shell = New-Object -ComObject WScript.Shell; $shortcut = $shell.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\HybridOps.Core.lnk'); $shortcut.TargetPath = $launcherPath; $shortcut.WorkingDirectory = $env:USERPROFILE; $shortcut.IconLocation = $iconPath + ',0'; $shortcut.Description = 'Open HybridOps.Core in Ubuntu'; $shortcut.Save()"
  if errorlevel 1 (
    echo WARN: unable to create the HybridOps.Core desktop shortcut.
  ) else (
    set "SHORTCUT_CREATED=true"
    if not "!SHORTCUT_EXISTS!"=="true" (
      echo Desktop shortcut created: HybridOps.Core
    )
  )
)

if exist "%WSL_SETUP_MARKER%" (
  powershell.exe -NoProfile -Command "Get-Process -Name 'wslsettings' -ErrorAction SilentlyContinue | ForEach-Object { [void]$_.CloseMainWindow() }"
  del /q "%WSL_SETUP_MARKER%" >nul 2>&1
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
