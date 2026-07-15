@echo off
rem purpose: Open HybridOps.Core in its Ubuntu WSL2 environment.
rem maintainer: HybridOps.Tech

wsl.exe -d Ubuntu-24.04 --cd ~
if errorlevel 1 (
  echo Unable to open Ubuntu-24.04.
  echo Confirm its state with: wsl --list --verbose
  pause
)
