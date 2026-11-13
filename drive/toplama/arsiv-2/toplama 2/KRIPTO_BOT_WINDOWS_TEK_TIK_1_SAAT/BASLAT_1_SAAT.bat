@echo off
chcp 65001 >nul
cd /d "%~dp0"
title KRIPTO-BOT - 1 Saatlik Paper Testi

echo ================================================================
echo KRIPTO-BOT v7.8 - WINDOWS TEK TIK 1 SAATLIK PAPER TESTI
echo ================================================================
echo.
echo Bu pencere test bitene kadar acik kalmalidir.
echo Telegram ve WhatsApp bu testte kullanilmayacaktir.
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows_baslat_1_saat.ps1"
set "BOT_RC=%ERRORLEVEL%"

echo.
if "%BOT_RC%"=="0" (
  echo ISLEM TAMAMLANDI. Sonuc klasoru Windows Gezgini'nde acildi.
) else (
  echo TEST BASARILI TAMAMLANAMADI. Hata raporu sonuc klasorundedir.
)
echo.
echo Bu pencereyi kapatmak icin bir tusa basin.
pause >nul
exit /b %BOT_RC%
