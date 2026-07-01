# DFpoke - Delta Force Card Tracker

[🇨🇳 中文说明](README_CN.md)

A web-based card collection tracker for the Delta Force (三角洲行动) playing card event. Players collect 54 playing cards + 1 card box (55 total), and this app helps track progress.

**Live demo:** [http://1.12.249.7:8080](http://1.12.249.7:8080)

## Screenshots

![DFpoke Screenshot](static/screenshot.png)

## Features

### Card Tracker
Each registered user gets a personal tracker page at `/<username>`. Cards are displayed in a grid layout (13 per row by suit), with special cards (Black Joker, Red Joker, Card Box) in a separate section. Click any card to toggle owned/unowned status. A progress bar and counter show your collection progress in real time.

### Leaderboard
The homepage displays a ranked leaderboard of all players sorted by collection count. Players can toggle their visibility on the leaderboard from their tracker page via a switch.

### OCR Screenshot Recognition
Upload a game inventory screenshot and the app automatically recognizes which cards you own. Uses **Baidu OCR** (high-accuracy mode) as the primary engine, with **Tesseract.js** as a browser-side fallback. Images are compressed client-side before upload for faster processing. The parser uses strict matching — it prioritizes precision over recall to avoid false positives.

### Filter & View
Filter cards by status: All / Missing / Owned. Suit sections with no visible cards are automatically hidden. Useful for quickly checking which cards you still need.

### Daily Keywords
Automatically fetches and displays the daily password/keyword codes from the Delta Force API. Updates at midnight (CST) each day.

### Announcements
A scrolling announcement ticker at the bottom of every page. Shows the 5 most recent events when a player collects a rare card (Black Joker, Red Joker, or Card Box) or completes the full collection. Each event is recorded once per user to prevent duplicates.

### PWA Support
Installable as a Progressive Web App. Add to your homescreen for a fullscreen, app-like experience. Includes an in-app guide (📲 button) with step-by-step instructions for both iOS and Android.

## Tech Stack

- **Backend:** Python Flask + SQLite (WAL mode, busy_timeout for concurrency)
- **Server:** Gunicorn with gthread workers, auto-recycling via `--max-requests`
- **OCR:** Baidu Cloud OCR API (accurate_basic) / Tesseract.js
- **Frontend:** Vanilla HTML/CSS/JS, no framework, mobile-first responsive design

## Quick Start

```bash
# Clone
git clone https://github.com/LH44666/DFpoke.git
cd DFpoke

# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run
python app.py
```

Open [http://localhost:8080](http://localhost:8080)

## Environment Variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | Flask session secret key |
| `BAIDU_API_KEY` | Baidu OCR API key (optional, enables screenshot recognition) |
| `BAIDU_SECRET_KEY` | Baidu OCR secret key (optional) |

## Deploy (Ubuntu + systemd)

1. Copy `dfpoke.service` to `/etc/systemd/system/`
2. Edit the service file with your API keys and paths
3. Run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable dfpoke
sudo systemctl start dfpoke
```

## License

MIT
