# IBDLabel

A single-file, browser-based annotation tool for labeling IBD (Crohn's disease and ulcerative colitis) endoscopy frames. No server, no build step, no upload — open the HTML file in a browser and start labeling. Everything runs and stays on your machine.

## What it does

IBDLabel lets a reader step through a folder of endoscopy still frames and record structured clinical annotations for each one: disease activity scores, descriptor-level findings, image quality/limitations, equipment metadata, free-text notes, tags, and pixel-level polygon segmentations of lesions. Labels are auto-saved as you go and can be exported to JSON/CSV, or written directly back into the source folder.

## Features

- **Two disease workflows**
  - **Ulcerative colitis** — Mayo endoscopic subscore (0–3) plus UCEIS-style descriptors: erythema, vascular pattern, friability, spontaneous bleeding, ulcer extent, mucopus, mucosal oedema, and mucosal surface/granularity.
  - **Crohn's disease** — SES-CD style scoring per segment: ulceration size, ulcerated surface, ulcer type, affected surface, and stenosis, with a running segment score.
- **Mucosal/lesion feature checklists** tailored to each disease (e.g. cobblestoning, pseudopolyps, fistula opening, skip lesions for CD; erosions, granularity, deep ulcers for UC).
- **Polygon segmentation mode** — draw, reposition, label, and delete freeform polygons directly on the image to mark lesions or regions of interest.
- **Common metadata fields** — bowel segment/location, frame informativeness, reasons for non-informative frames (motion blur, debris, over/underexposure, etc.), light mode (WLE/BLI/LCI/NBI/TXI), manufacturer, visible tools, reader confidence, free-text notes, and custom tags.
- **Filmstrip navigation** with per-frame status dots (color-coded by severity/score), filters for unlabeled and informative-only frames, and keyboard shortcuts.
- **Zoom & pan** on the image viewer for close inspection.
- **Local-first storage** — annotations persist automatically in local artifact storage as you work (no data leaves the browser).
- **Import/export** — export all annotations to `annotations.json` and `annotations.csv`, or import a previously exported JSON file to resume/merge work.
- **Direct folder save** (Chromium browsers only) — using the File System Access API, IBDLabel can write `annotations.json`/`.csv` straight back into the folder the images were opened from, and will auto-load an existing `annotations.json` found there.

## Getting started

1. Open `ibdlabel.html` in a browser (Chrome/Edge recommended for full functionality).
2. Load images one of two ways:
   - **Open folder** — grants read/write access to a local folder (e.g. a OneDrive-synced folder of frames) and enables direct "Save to folder."
   - **Pick images** — a simpler file picker for individual images; works in any modern browser, but labels must be exported manually (no folder write access).
3. Step through frames using the filmstrip, arrow keys, or on-screen nav arrows.
4. Fill in the annotation panel on the right for each frame.
5. Switch to the **Segment** tab to draw lesion polygons on the current frame.
6. Save your work:
   - **Save to folder** — writes `annotations.json` + `annotations.csv` into the opened folder (only available if you used "Open folder").
   - **Export** — downloads `annotations.json` + `annotations.csv` to your downloads folder (works regardless of how images were loaded).
7. Use **Import** to load a previously exported `annotations.json` and resume or merge labels.

> Browser support note: folder access and direct save require the File System Access API (`window.showDirectoryPicker`), which is currently Chromium-only (Chrome, Edge, Opera, etc.). In other browsers, use "Pick images" and export manually.

## Keyboard shortcuts

| Key | Action |
|---|---|
| `→` / `j` | Next frame |
| `←` / `k` | Previous frame |
| `0`–`3` | Set Mayo score (when disease = UC) |
| `=` / `+` | Zoom in |
| `-` | Zoom out |
| `Shift` + `0` | Reset zoom/pan |

Click the `?` button in the top bar for an in-app reminder of these shortcuts.

## Data model

Each frame's annotation is keyed by filename and includes:

```
{
  disease: "UC" | "CD",
  mayo: 0|1|2|3|null,
  uc: { erythema, vascular, friability, spontBleed, ulcerExtent, mucopus, mucoOedema, mucoSurf },
  ses: { ulcerSize, ulcSurface, ulcerType, affSurface, narrowing },
  ucFeat: { ... },       // checked UC mucosal features
  cdFeat: { ... },       // checked CD lesion features
  region: string,        // bowel segment
  quality: "Informative" | "Non-informative",
  limitations: { ... },  // reasons for poor image quality
  limitationsOther: string,
  light: string,         // imaging light mode
  mfr: string,           // scope manufacturer
  tools: { ... },        // visible instruments
  conf: "Low"|"Medium"|"High",
  notes: string,
  tags: string[],
  polygons: [{ id, label, points: [{x,y}, ...] }],
  ts: number             // last-modified timestamp
}
```

The exported CSV flattens this structure into one row per frame for easy import into spreadsheets or stats software.

## Privacy

Images are read directly from disk into the browser and are never uploaded anywhere. Annotations are stored locally (browser-side storage and/or the local folder you choose) unless you manually export and share the resulting files.

## Status

v1.1 · local-only tool, no backend required.
