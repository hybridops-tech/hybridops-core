@echo off
setlocal EnableExtensions
title HybridOps.Core
powershell.exe -NoProfile -Command "$Host.UI.RawUI.WindowTitle = 'HybridOps.Core'; $dots = 0; $process = Start-Process -FilePath 'wsl.exe' -WindowStyle Hidden -PassThru -ArgumentList @('-d','Ubuntu-24.04','--cd','~','--','true'); while (-not $process.HasExited) { $dots = ($dots %% 3) + 1; Write-Host -NoNewline ([char]13 + 'Starting HybridOps.Core' + ('.' * $dots) + (' ' * (3 - $dots))); Start-Sleep -Milliseconds 300 }; $process.WaitForExit(); Clear-Host; Write-Host 'HybridOps.Core ready.'; & wsl.exe -d Ubuntu-24.04 --cd '~' -- bash -c 'exec bash --noprofile --rcfile ~/.hybridops/config/windows-shell.rc -i'; exit $LASTEXITCODE"
