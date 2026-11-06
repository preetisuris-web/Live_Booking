#!/usr/bin/env python3
"""
3-hour looping Facebook + Instagram live stream of your designs.

Order of the stream (each block = 20 designs):
  latest 20 -> top-stock 1-20 -> latest 20 -> top-stock 21-40 -> latest 20 -> top-stock 41-60 ...
until the total length reaches --hours (default 3). When the stock list runs out
it starts again from the highest-stock designs.

Each design becomes one clip: its video (Video Link) if it can be downloaded,
otherwise its photo (Image Link) shown for a few seconds. Design No and price
are printed on every clip.

Run this on a machine that stays on (your Hetzner server), NOT your laptop:
  sudo apt-get install -y ffmpeg fonts-dejavu-core python3
  pip3 install yt-dlp            # only needed if Video Links are YouTube
  export FB_KEY='rtmps://live-api-s.facebook.com:443/rtmp/FB-xxxx'
  export IG_KEY='rtmps://edgetee-upload-xxx.xx.fbcdn.net:443/rtmp/xxxx'
  nohup python3 live_stream.py > live.log 2>&1 &

Then you can switch your laptop off. Watch progress with:  tail -f live.log
Stop early with:  pkill -f live_stream.py; pkill ffmpeg

Test without going live:  python3 live_stream.py --dry-run
  (writes the first few minutes to preview.mp4 so you can check it)
"""
import argparse, csv, io, os, re, shutil, subprocess, sys, urllib.request

SHEET_ID = "1wcR2TDqy24SALIkHTnwXpLe0RHKeu2EXZoPyraZBtdM"   # same sheet as index.html
SHEET_NAME = "Products"
W, H, FPS = 720, 1280, 30          # vertical 9:16, accepted by both Instagram and Facebook
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def log(*a):
    print(*a, flush=True)


# ---------- reading the sheet ----------
def load_rows(csv_path=None):
    if csv_path:
        text = open(csv_path, encoding="utf-8").read()
    else:
        url = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq"
               f"?tqx=out:csv&sheet={SHEET_NAME}")
        text = urllib.request.urlopen(url, timeout=60).read().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in rows]


def find_col(rows, *needles):
    if not rows:
        return None
    for col in rows[0].keys():
        low = col.lower()
        if any(n in low for n in needles):
            return col
    return None


def number(s):
    m = re.search(r"-?\d+(\.\d+)?", s or "")
    return float(m.group()) if m else 0.0


def total_stock(s):
    """'5' -> 5 ; 'S:2, M:3, L:1' -> 6 ; '' -> 0"""
    nums = re.findall(r"\d+(?:\.\d+)?", s or "")
    if not nums:
        return 0.0
    # 'S:2 M:3' style -> sum ; plain number -> that number
    return sum(float(n) for n in nums) if re.search(r"[:=]", s) else float(nums[0])


# ---------- making clips ----------
def drive_id(url):
    m = re.search(r"/d/([A-Za-z0-9_-]+)", url) or re.search(r"[?&]id=([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else None


def download(url, dest):
    if not url:
        return None
    try:
        if "youtu" in url:
            if not shutil.which("yt-dlp"):
                return None
            subprocess.run(["yt-dlp", "-q", "-f", "mp4/best", "-o", dest, url],
                           check=True, timeout=300)
            return dest if os.path.exists(dest) else None
        did = drive_id(url) if "drive.google" in url else None
        if did:
            url = f"https://drive.usercontent.google.com/download?id={did}&export=download&confirm=t"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        # Drive sometimes returns an HTML warning page instead of the file
        with open(dest, "rb") as f:
            if f.read(15).lower().startswith((b"<!doctype", b"<html")):
                return None
        return dest
    except Exception as e:
        log("   download failed:", url[:80], e)
        return None


def esc(t):
    return t.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")


def make_clip(p, work, max_video_sec, photo_sec):
    """Returns path of a normalised clip (same codec settings for every clip)."""
    key = re.sub(r"[^A-Za-z0-9_-]", "_", p["design"] or "x")
    out = os.path.join(work, f"clip_{key}.mp4")
    if os.path.exists(out):
        return out
    label = f"Design {p['design']}" + (f"   Rs {p['price']}" if p["price"] else "")
    sizes = f"Sizes {p['sizes']}" if p["sizes"] else ""
    text = (f"drawbox=x=0:y=ih-230:w=iw:h=230:color=black@0.55:t=fill,"
            f"drawtext=fontfile={FONT}:text='{esc(label)}':fontcolor=white:fontsize=52:"
            f"x=(w-text_w)/2:y=h-200")
    if sizes:
        text += (f",drawtext=fontfile={FONT}:text='{esc(sizes)}':fontcolor=white:"
                 f"fontsize=38:x=(w-text_w)/2:y=h-120")
    fit = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
           f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS},format=yuv420p")
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-b:v", "2500k", "-maxrate", "2500k",
           "-bufsize", "5000k", "-g", str(FPS * 2), "-keyint_min", str(FPS * 2),
           "-sc_threshold", "0", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]

    src = download(p["video"], os.path.join(work, f"src_{key}.vid"))
    if src:
        has_audio = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=index", "-of", "csv=p=0", src], capture_output=True, text=True).stdout.strip()
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src]
        if not has_audio:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        cmd += ["-t", str(max_video_sec), "-vf", fit + "," + text, "-map", "0:v:0",
                "-map", "0:a:0" if has_audio else "1:a:0", "-shortest"] + enc + [out]
        if subprocess.run(cmd).returncode == 0:
            return out
        log("   video unusable, falling back to photo")

    img = download(p["image"], os.path.join(work, f"img_{key}.jpg"))
    if not img:
        log(f"   skipping design {p['design']}: no usable video or photo")
        return None
    cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", img,
           "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
           "-t", str(photo_sec), "-vf", fit + "," + text, "-map", "0:v", "-map", "1:a"] + enc + [out]
    return out if subprocess.run(cmd).returncode == 0 else None


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=3)
    ap.add_argument("--block", type=int, default=20, help="designs per block")
    ap.add_argument("--csv", help="use a local CSV export instead of the Google Sheet")
    ap.add_argument("--stock-col", help="name of the stock column (auto-detected if omitted)")
    ap.add_argument("--latest-by", default="design",
                    help="'design' = highest Design No is latest; 'position' = lowest Position "
                         "is latest; or any other column name (highest value = latest)")
    ap.add_argument("--max-video-sec", type=int, default=20)
    ap.add_argument("--photo-sec", type=int, default=8)
    ap.add_argument("--work", default=os.path.expanduser("~/live_work"))
    ap.add_argument("--dry-run", action="store_true",
                    help="no streaming; write first 3 minutes to preview.mp4")
    a = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not installed: sudo apt-get install -y ffmpeg")
    if not os.path.exists(FONT):
        sys.exit("font missing: sudo apt-get install -y fonts-dejavu-core")
    targets = [k for k in (os.environ.get("FB_KEY"), os.environ.get("IG_KEY")) if k]
    if not a.dry_run and not targets:
        sys.exit("Set FB_KEY and/or IG_KEY (full rtmps://... URL including the stream key)")
    os.makedirs(a.work, exist_ok=True)

    rows = load_rows(a.csv)
    log(f"Loaded {len(rows)} rows from sheet")
    stock_col = a.stock_col or find_col(rows, "stock", "qty", "quantity", "pcs", "pieces")
    if not stock_col:
        sys.exit("No stock column found in the sheet. Pass --stock-col 'Your Column Name'. "
                 f"Columns are: {list(rows[0].keys()) if rows else []}")
    log(f"Stock column: {stock_col!r}   latest by: {a.latest_by!r}")

    designs = []
    for r in rows:
        d = {"design": r.get("Design No") or r.get("Design") or "",
             "price": r.get("Price") or r.get("MRP") or "",
             "sizes": r.get("Available Sizes") or r.get("Sizes") or "",
             "image": r.get("Image Link") or r.get("Image") or "",
             "video": r.get("Video Link") or "",
             "position": number(r.get("Position", "")),
             "stock": total_stock(r.get(stock_col, "")),
             "row": r}
        if d["design"] and (d["image"] or d["video"]):
            designs.append(d)
    if not designs:
        sys.exit("No designs with a Design No and a photo/video link")

    if a.latest_by == "design":
        latest = sorted(designs, key=lambda d: number(d["design"]), reverse=True)
    elif a.latest_by == "position":
        latest = sorted(designs, key=lambda d: d["position"])
    else:
        latest = sorted(designs, key=lambda d: number(d["row"].get(a.latest_by, "")), reverse=True)
    latest = latest[:a.block]
    by_stock = [d for d in sorted(designs, key=lambda d: d["stock"], reverse=True) if d["stock"] > 0]
    stock_blocks = [by_stock[i:i + a.block] for i in range(0, len(by_stock), a.block)] or [[]]

    log("Latest 20:", ", ".join(d["design"] for d in latest))
    for i, b in enumerate(stock_blocks, 1):
        log(f"Stock block {i}:", ", ".join(f"{d['design']}({d['stock']:g})" for d in b))

    log("Preparing clips (one-time, cached in", a.work, ")...")
    clip = {}
    for d in {d["design"]: d for d in latest + by_stock}.values():
        log(" -", d["design"])
        c = make_clip(d, a.work, a.max_video_sec, a.photo_sec)
        if c:
            clip[d["design"]] = (c, duration(c))

    # build the running order until we reach the target length
    target = a.hours * 3600 if not a.dry_run else 180
    order, total, n = [], 0.0, 0
    while total < target:
        block = latest if n % 2 == 0 else stock_blocks[(n // 2) % len(stock_blocks)]
        added = False
        for d in block:
            if d["design"] in clip and total < target:
                order.append(clip[d["design"]][0])
                total += clip[d["design"]][1]
                added = True
        if not added and n > 2:
            sys.exit("No clips could be made; check the photo/video links are public")
        n += 1
    playlist = os.path.join(a.work, "playlist.txt")
    with open(playlist, "w") as f:
        for c in order:
            f.write(f"file '{c}'\n")
    log(f"Running order: {len(order)} clips, {total / 60:.0f} minutes, {n} blocks")

    base = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-stats", "-re",
            "-f", "concat", "-safe", "0", "-i", playlist, "-map", "0:v", "-map", "0:a",
            "-c", "copy"]
    if a.dry_run:
        out = os.path.join(os.getcwd(), "preview.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", playlist, "-c", "copy", out], check=True)
        log("Dry run done ->", out)
        return
    tee = "|".join(f"[f=flv:onfail=ignore]{t}" for t in targets)
    log(f"GOING LIVE to {len(targets)} destination(s) for {total / 3600:.2f} h")
    rc = subprocess.run(base + ["-f", "tee", tee]).returncode
    log("Stream ended, ffmpeg exit code", rc)


if __name__ == "__main__":
    main()
