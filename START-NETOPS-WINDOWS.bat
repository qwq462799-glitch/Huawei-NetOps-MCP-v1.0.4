@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo ==============================================
echo  Huawei NetOps MCP - Windows One-Click Launcher
echo ==============================================
echo.
REM 默认：Windows 本机 MCP，适合传统 eNSP / eNSP Pro 在本机运行。
REM 如 MCP 已部署在 Ubuntu，请取消下面两行注释并填写 SSH 目标及远程目录：
REM set "NETOPS_REMOTE_SSH_TARGET=ubuntuuser@192.168.1.20"
REM set "NETOPS_REMOTE_PROJECT_ROOT=/opt/huawei-netops-mcp"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\oneclick-windows.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [ERROR] Huawei NetOps MCP 启动失败，退出码：%RC%
  pause
)
endlocal & exit /b %RC%
