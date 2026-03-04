@echo off
title PixelStream-OS - Launcher
echo ==========================================
echo    PIXELSTREAM-OS - APP LAUNCHER
echo ==========================================
echo.
echo 1. Opening the Dashboard in your browser...
start http://localhost:8501
echo.
echo 2. Starting the server...
echo.
echo NOTE: If you see "http://0.0.0.0:8501" in the text below, 
echo DO NOT click it. Use the window that just opened instead.
echo.
python -m streamlit run app.py --server.address 0.0.0.0 --server.headless true
echo.
echo Server stopped.
pause
