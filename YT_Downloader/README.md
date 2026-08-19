# LiquidGlass Downloader

LiquidGlass Downloader is a cross-platform application for downloading online videos.  It ships with a clean CustomTkinter GUI and a simple CLI so you can queue, track and manage your downloads with ease.

## Features
- Queue multiple URLs and monitor progress
- Color‑coded status indicators with percentage progress
- History export to CSV or JSON
- Configurable themes, formats and concurrent downloads
- Optional cookies file and custom User-Agent for restricted videos
- Forces YouTube web player client to reduce 403 errors

## Installation
```bash
pip install -e .
```

## Usage
Launch the graphical interface:
```bash
liquidglass-gui
```
Run from the command line:
```bash
liquidglass-downloader <url> [<url> ...]
```
