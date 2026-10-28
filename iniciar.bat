@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py -m metaclean & goto fim)
where python >nul 2>nul && (python -m metaclean & goto fim)
echo Python nao encontrado. Instale em https://www.python.org/downloads/ (marque "Add python.exe to PATH").
:fim
pause
