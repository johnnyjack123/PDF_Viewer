# FluentPDF

Moderner PDF-Viewer im Windows 11 Fluent Design-Stil.

## Schnellstart

```bash
pip install -r requirements.txt
python fluentpdf.py
```

## Features
- Bibliothek mit Cover-Thumbnails
- Lesefortschritt wird automatisch gespeichert
- Direkter Einstieg auf der letzten Seite beim Oeffnen
- Seiteneingabe per Textfeld + Enter
- Zoom 50%-400% (Tasten: + / -)
- Navigation per Pfeiltasten
- Auto Dark/Light Mode (folgt Windows-Systemthema)
- Live-Suche in der Bibliothek

## Datenspeicherung
Alle Daten unter ~/.fluentpdf/
- library.json  -> Liste der PDFs
- progress.json -> Lesefortschritt je PDF
