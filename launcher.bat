@echo off
setlocal

:: Ordner dieser Batch-Datei als Arbeitsverzeichnis setzen
cd /d "%~dp0"

:: Pruefen ob venv-Ordner existiert
if not exist "venv\" (
    echo [FluentPDF] Kein venv gefunden - erstelle neues venv...
    python -m venv venv
    if errorlevel 1 (
        echo [FEHLER] venv konnte nicht erstellt werden. Ist Python installiert?
        pause
        exit /b 1
    )
    echo [FluentPDF] Installiere Abhaengigkeiten...
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [FEHLER] pip install fehlgeschlagen.
        pause
        exit /b 1
    )
    echo [FluentPDF] Installation abgeschlossen.
) else (
    call venv\Scripts\activate.bat
)

echo [FluentPDF] Starte App...
python fluentpdf.py