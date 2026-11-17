# Video Downloader

**Incolla il link di un video e scaricalo come video (MP4) o come audio (MP3, M4A, Opus, FLAC, WAV).**

Applicazione per Windows 10/11 (64 bit), con tema chiaro e scuro. Funziona con YouTube, TikTok, Instagram, Facebook, X, Vimeo, Reddit, Twitch, SoundCloud e centinaia di altri siti, grazie a [yt-dlp](https://github.com/yt-dlp/yt-dlp) e [FFmpeg](https://ffmpeg.org), inclusi nell'installer.

> Scarica solo contenuti che hai il diritto di salvare (tuoi, con licenza libera o con il permesso dell'autore).

## Download
L'installer è nella sezione **Releases** del repository: scarica `VideoDownloader-Setup-1.0.0.exe` ed eseguilo (non servono diritti di amministratore).

## Come si usa
1. Incolla il link (o premi **Incolla**, o trascina il link nella finestra).
2. Scegli **Video (MP4)** con la qualità desiderata, oppure **Solo audio** con formato e qualità.
3. Premi **Scarica**. Ogni download ha una barra di avanzamento con percentuale, velocità e tempo rimasto, e il pulsante per annullarlo.

I file vengono salvati in `Download\Video Downloader` (si cambia dal pulsante in basso).

## Scorciatoie
`Ctrl+L` campo link · `Ctrl+Maiusc+V` incolla e analizza · `Invio` analizza · `Ctrl+Invio` scarica · `Ctrl+O` apri cartella · `Ctrl+Maiusc+O` cambia cartella · `F1` informazioni

## Limiti
- Un link alla volta: le playlist e i profili vanno scaricati video per video.
- I contenuti privati o con limiti di età richiedono l'accesso: da **Impostazioni** si possono usare i cookie del browser in cui sei già connesso (Firefox è il più affidabile).
- I siti cambiano spesso: se un sito smette di funzionare serve una nuova versione del programma (con yt-dlp aggiornato).

## Eseguire dal sorgente
```
pip install PySide6 yt-dlp yt-dlp-ejs truststore pyinstaller
python video_downloader.py
```
Servono `ffmpeg` (nel PATH o in `C:\ffmpeg`) e Node.js (per YouTube). Installer: `python build.py` (richiede Inno Setup 6).

## Licenza
MIT, © 2026 Cesa028. Componenti di terze parti (yt-dlp, FFmpeg, Qt/PySide6, Node.js, truststore) con le rispettive licenze in `licenses/`.
