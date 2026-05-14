@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONWARNINGS=ignore
.venv\Scripts\python.exe ui\pyside\main.py
