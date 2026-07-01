import cv2
import re
from pathlib import Path
from typing import Optional, Union, Dict, Tuple

import pandas as pd
import pytesseract
from pytesseract import image_to_string


# ===================== OCR (Olympus) helpers =====================

def clean_text(t: str) -> str:
    t = t.upper().replace("O", "0").replace("S", "5").replace("I", "1").replace("L", "1")
    return re.sub(r"[^0-9:\-\n ]", " ", t)


def parse_olympus_hms(
    text: str,
    prefer_zero_hours: bool = True,
    hint_sec: float = 180
) -> Optional[int]:
    """
    Olympus overlay usually contains HH:MM:SS.
    Returns stopwatch seconds if found, else None.
    """
    t = clean_text(text)
    tokens = re.findall(r"\b(\d{2}):([0-5]\d):([0-5]\d)\b", t)
    if not tokens:
        return None

    if prefer_zero_hours:
        for hh, mm, ss in tokens:
            if hh == "00":
                return int(hh) * 3600 + int(mm) * 60 + int(ss)

    target = int(hint_sec) % 3600
    best: Optional[int] = None
    best_d = 10**9
    for hh, mm, ss in tokens:
        val = int(hh) * 3600 + int(mm) * 60 + int(ss)
        d = abs((val % 3600) - target)
        if d < best_d:
            best, best_d = val, d
    return best


# ROI for Olympus left panel from your old script
LEFT_PANEL_ROI = (0.00, 1.00, 0.00, 0.32)  # (y0,y1,x0,x1) fractions


def crop_frac(img, roi):
    y0, y1, x0, x1 = roi
    H, W = img.shape[:2]
    return img[int(H * y0):int(H * y1), int(W * x0):int(W * x1)]


def ocr_left_panel_text(frame_bgr, save_debug: Optional[str] = None) -> str:
    roi = crop_frac(frame_bgr, LEFT_PANEL_ROI)
    if roi.size == 0:
        return ""

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)

    scale = 1.6
    gray = cv2.resize(
        gray,
        (int(gray.shape[1] * scale), int(gray.shape[0] * scale)),
        interpolation=cv2.INTER_CUBIC,
    )

    candidates = []
    for thflag in (cv2.THRESH_BINARY_INV, cv2.THRESH_BINARY):
        _, thr = cv2.threshold(gray, 0, 255, thflag | cv2.THRESH_OTSU)
        if save_debug and thflag == cv2.THRESH_BINARY_INV:
            cv2.imwrite(save_debug, thr)

        txt = image_to_string(
            thr,
            config="--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789:",
        )
        candidates.append(txt)

    merged = "\n".join(candidates)
    return clean_text(merged)


def find_olympus_offset_single(
    video_path: Union[str, Path],
    probe_times: Tuple[int, int, int] = (180, 120, 240),
    save_debug_dir: Optional[Union[str, Path]] = "ocr_debug",
) -> Optional[float]:
    """
    Probes a few VIDEO times, OCRs stopwatch, and returns:
        offset = video_time - stopwatch_time
    """
    video_path = Path(video_path)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"ERROR: Cannot open video: {video_path}")
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    hit: Optional[float] = None

    for t in probe_times:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
        ok, frame = cap.read()
        if not ok:
            continue

        dbg_path = None
        if save_debug_dir:
            Path(save_debug_dir).mkdir(parents=True, exist_ok=True)
            dbg_path = str(Path(save_debug_dir) / f"{video_path.stem}_leftpanel_t{t}.png")

        txt = ocr_left_panel_text(frame, save_debug=dbg_path)
        sw = parse_olympus_hms(txt, prefer_zero_hours=True, hint_sec=t)

        print(f"\nOCR probe @ video t={t}s")
        print(f"OCR text:\n{txt.strip()}")
        print(f"Parsed stopwatch seconds: {sw}")

        if sw is not None:
            offset = float(t) - float(sw)
            print(f"Offset found: video({t}) - stopwatch({sw}) = {offset:+.2f}s")
            hit = offset
            break

    cap.release()

    if hit is None:
        print(f"OCR couldn't read stopwatch at probe times {probe_times}.")
    return hit


# ===================== Frame extraction (uses stopwatch times) =====================

def normalize_hms(t: str) -> str:
    """
    Accepts 'H:MM:SS' or 'HH:MM:SS' and returns 'HH:MM:SS' (for display only).
    """
    t = str(t).strip()
    parts = t.split(":")
    if len(parts) != 3:
        raise ValueError(f"Time must be H:MM:SS or HH:MM:SS, got '{t}'")
    h, m, s = parts
    h = int(h)
    m = int(m)
    s = int(float(s))
    if not (0 <= m <= 59 and 0 <= s <= 59):
        raise ValueError(f"Invalid MM:SS in '{t}'")
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_stopwatch_time_hms(t: str) -> int:
    """
    IMPORTANT: Excel auto-formatted bare 'M:SS' entries (e.g. typed '9:51')
    as time-of-day 'H:MM:SS' (e.g. stored/displayed as 09:51:00). The
    trailing :00 seconds field is an Excel artifact, not real data - the
    displayed HOUR digit is actually MINUTES and the displayed MINUTE
    digit is actually SECONDS off the on-screen stopwatch overlay.
    So we convert HH:MM:00 -> HH*60 + MM seconds (NOT HH*3600 + MM*60).
    """
    t = normalize_hms(t)
    hh, mm, ss = map(int, t.split(":"))
    return hh * 60 + mm


def is_valid_mes(value) -> bool:
    if pd.isna(value):
        return False
    s = str(value).strip().upper()
    if s in ("", "NA", "N/A", "NAN"):
        return False
    return True


def clean_mes_label(value) -> str:
    """Normalize MES value for use in a filename, e.g. 2.0 -> '2'."""
    s = str(value).strip()
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
        return s.replace(".", "p")
    except ValueError:
        return re.sub(r"[^0-9A-Za-z]+", "", s) or "unk"


def extract_mes_intervals_for_video(
    video_path: Union[str, Path],
    intervals: pd.DataFrame,   # rows for this one video: Start, End, MES
    interval: float = 1 / 3,   # 1/TARGET_FPS
    output_root: Union[str, Path] = "MES_frame_extraction",
    probe_times: Tuple[int, int, int] = (180, 120, 240),
    debug_ocr_dir: Optional[Union[str, Path]] = "ocr_debug",
):
    """
    Same approach as extract_frames_by_stopwatch in the ulcer script:
    find the OCR offset once for the video, then walk each MES interval
    (skipping NA), converting stopwatch Start/End -> video seconds with
    that offset, and saving frames every `interval` seconds.

    If OCR cannot find the stopwatch overlay, this raises an error
    (no offset=0 fallback) so the caller can skip/report the video.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    offset = find_olympus_offset_single(
        video_path,
        probe_times=probe_times,
        save_debug_dir=debug_ocr_dir
    )
    if offset is None:
        raise RuntimeError(
            f"OCR could not read stopwatch overlay for {video_path.name} "
            f"at probe times {probe_times}. Aborting this video."
        )

    record_id = video_path.stem
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0.0

    out_dir = Path(output_root) / record_id
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n==============================")
    print(f"Video: {video_path.name}")
    print(f"Record: {record_id}")
    print(f"OCR offset (video - stopwatch): {offset:+.2f}s")
    print(f"Duration: {duration:.2f}s")
    print("==============================\n")

    seq = 0
    total_frame_count = 0

    for _, row in intervals.iterrows():
        mes_raw = row["MES"]
        if not is_valid_mes(mes_raw):
            continue

        start_sw = str(row["Start"]).strip()
        end_sw = str(row["End"]).strip()

        try:
            start_sw_sec = parse_stopwatch_time_hms(start_sw)
            end_sw_sec = parse_stopwatch_time_hms(end_sw)
        except ValueError as e:
            print(f"[SKIP interval] {record_id}: {e}")
            continue

        if start_sw_sec >= end_sw_sec:
            continue

        start_vid = max(0.0, start_sw_sec + offset)
        end_vid = max(0.0, end_sw_sec + offset)

        if duration > 0:
            start_vid = min(start_vid, duration)
            end_vid = min(end_vid, duration)

        if start_vid >= end_vid:
            print(
                f"[SKIP interval] {record_id}: window invalid after offset "
                f"start={start_vid:.2f}s end={end_vid:.2f}s (duration={duration:.2f}s)"
            )
            continue

        mes_label = clean_mes_label(mes_raw)

        print(f"Stopwatch window: {normalize_hms(start_sw)} -> {normalize_hms(end_sw)}  (MES={mes_label})")
        print(f"Video window: {start_vid:.2f}s -> {end_vid:.2f}s")

        current = start_vid
        while current <= end_vid:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(current * fps))
            ret, frame = cap.read()
            if not ret:
                break
            seq += 1
            filename = f"{record_id}_{mes_label}_{seq:06d}.jpg"
            cv2.imwrite(str(out_dir / filename), frame)
            total_frame_count += 1
            current += interval

    cap.release()

    print(f"\n✓ Extracted {total_frame_count} frames total to {out_dir}")
    return out_dir, total_frame_count


# ===================== Excel batch runner =====================

VIDEO_EXTS = (".mov", ".mp4", ".m4v", ".avi", ".mkv")


def build_video_index(video_dir: Union[str, Path]) -> Dict[str, Path]:
    """
    Map record_id -> video file path by scanning VIDEO_DIR.
    Matches by file stem exactly (vid_03_5162.mov -> record_id vid_03_5162).
    """
    video_dir = Path(video_dir)
    idx: Dict[str, Path] = {}
    for p in video_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith(("._", ".")):
            continue
        if p.suffix.lower() not in VIDEO_EXTS:
            continue
        idx[p.stem] = p
    return idx


def read_table(
    table_path: Union[str, Path],
    sheet_name: str = "Time intervals per video",
) -> pd.DataFrame:
    """
    Reads the 'Time intervals per video' sheet (two-row header).
    Expects columns: VIDEO ID, Start, End, MES
    """
    table_path = Path(table_path)
    df = pd.read_excel(table_path, sheet_name=sheet_name, header=1)
    df.columns = [str(c).strip() for c in df.columns]

    required = {"VIDEO ID", "Start", "End", "MES"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in '{sheet_name}': {sorted(missing)}")

    df = df.dropna(subset=["VIDEO ID", "Start", "End"])
    df["VIDEO ID"] = df["VIDEO ID"].astype(str).str.strip()
    df = df[df["VIDEO ID"] != ""]
    return df


def record_id_to_video_stem(record_id: str) -> str:
    """'03-5162' -> 'vid_03_5162'."""
    return "vid_" + record_id.strip().replace("-", "_")


def run_from_excel(
    table_path: Union[str, Path],
    video_dir: Union[str, Path],
    output_root: Union[str, Path] = "MES_frame_extraction",
    interval: float = 1 / 3,
    probe_times: Tuple[int, int, int] = (180, 120, 240),
    ocr_debug_dir: Union[str, Path] = "ocr_debug",
    sheet_name: str = "Time intervals per video",
):
    df = read_table(table_path, sheet_name=sheet_name)
    video_index = build_video_index(video_dir)

    print(f"Found {len(video_index)} video(s) under {Path(video_dir)}")
    print(f"Loaded {len(df)} row(s) from {Path(table_path).name} [{sheet_name}]\n")

    missing_videos = []
    ocr_failed_videos = []
    failed_videos = []

    for sheet_record_id in df["VIDEO ID"].unique():
        video_stem = record_id_to_video_stem(sheet_record_id)

        if video_stem not in video_index:
            missing_videos.append(sheet_record_id)
            print(f"[SKIP] No video found for VIDEO ID={sheet_record_id} (looked for {video_stem})")
            continue

        video_path = video_index[video_stem]
        intervals = df[df["VIDEO ID"] == sheet_record_id]

        try:
            extract_mes_intervals_for_video(
                video_path=video_path,
                intervals=intervals,
                interval=interval,
                output_root=output_root,
                probe_times=probe_times,
                debug_ocr_dir=ocr_debug_dir,
            )
        except RuntimeError as e:
            # OCR failure or unreadable video - error and skip, no fallback
            ocr_failed_videos.append(sheet_record_id)
            print(f"[ERROR] {sheet_record_id}: {e}")
        except Exception as e:
            failed_videos.append(sheet_record_id)
            print(f"[ERROR] {sheet_record_id}: {e}")

    if missing_videos:
        uniq = sorted(set(missing_videos))
        print(f"\nMissing videos for {len(uniq)} record_id(s): {uniq}")
    if ocr_failed_videos:
        uniq = sorted(set(ocr_failed_videos))
        print(f"\nOCR failed for {len(uniq)} record_id(s): {uniq}")
    if failed_videos:
        uniq = sorted(set(failed_videos))
        print(f"\nOther failures for {len(uniq)} record_id(s): {uniq}")

    print(f"\nDone.")


def main():
    # ============ USER SETTINGS (VS CODE) ============
    EXCEL_PATH = r"G:\\UC_Central-Reading_General-Data-MO.xlsx"
    SHEET_NAME = "Time intervals per video"

    VIDEO_DIR = r"G:\\"        # folder containing vids like vid_03_5162.mov
    OUTPUT_ROOT = "MES_frame_extraction"

    TARGET_FPS = 3
    INTERVAL = 1 / TARGET_FPS
    PROBE_TIMES = (180, 120, 240)  # seconds in video-time to probe for OCR offset
    OCR_DEBUG_DIR = "ocr_debug"
    # ===============================================

    # If Tesseract isn't on PATH on Windows, set this:
    pytesseract.pytesseract.tesseract_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

    run_from_excel(
        table_path=EXCEL_PATH,
        sheet_name=SHEET_NAME,
        video_dir=VIDEO_DIR,
        output_root=OUTPUT_ROOT,
        interval=INTERVAL,
        probe_times=PROBE_TIMES,
        ocr_debug_dir=OCR_DEBUG_DIR,
    )


if __name__ == "__main__":
    main()