@echo off
cd /d "%~dp0"
title Bot Studyosu - EXE yapici
echo ==================================================
echo    BOT STUDYOSU  -  TEK TIKLA EXE YAPICI
echo ==================================================
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo HATA: Python bulunamadi!
  echo Once https://www.python.org/downloads/ adresinden Python kur.
  echo Kurulumda "Add python.exe to PATH" kutusunu ISARETLE!
  pause
  exit /b 1
)
if not exist BotStudyosu.py (
  echo HATA: BotStudyosu.py bu klasorde yok!
  echo Bu dosyayi BotStudyosu.py ile AYNI klasore koy.
  pause
  exit /b 1
)
echo [1/3] PyInstaller kontrol ediliyor / kuruluyor...
python -m pip show pyinstaller >nul 2>nul
if errorlevel 1 python -m pip install --quiet pyinstaller
echo [2/3] EXE derleniyor (2-4 dakika surebilir, pencereyi KAPATMA)...
python -m PyInstaller --onefile --name BotStudyosu --clean --noconfirm ^
  --collect-all uvicorn --collect-all fastapi --collect-all pydantic ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  BotStudyosu.py
if errorlevel 1 (
  echo.
  echo HATA: derleme basarisiz - yukaridaki kirmizi satirlarin ekran
  echo goruntusunu alip gonder.
  pause
  exit /b 1
)
echo [3/3] Temizlik...
if exist BotStudyosu.spec del /q BotStudyosu.spec
echo.
echo   ==========================================================
echo    BITTI!  EXE burada:  dist\BotStudyosu.exe
echo   ==========================================================
echo   - Bu TEK dosyayi istedigin yere tasiyabilirsin.
echo   - Cift tikla: tarayici kendiliginden acilir (port 8899).
echo   - ayarlar.json / hafiza.json EXE'nin YANINA kaydedilir;
echo     kapatip actiginda her sey yerinde kalir.
echo   - Ilk acilista Windows Defender yavaslatinabilir, 5-10 sn bekle.
echo   - Ayni anda iki kopya acmaya gerek yok: biri calisirken
echo     cift tiklarsan tarayiciyi acar, ikinci kopya acmaz.
pause
