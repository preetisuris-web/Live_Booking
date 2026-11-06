#!/usr/bin/env python3
"""
3-hour looping Facebook + Instagram live stream of your designs, straight from the desk.

Order of the stream (each block = 20 designs):
  latest 20 -> top-stock 1-20 -> latest 20 -> top-stock 21-40 -> latest 20 -> top-stock 41-60 ...
until the total length reaches --hours (default 3). When the stock list runs out it starts
again from the highest-stock designs.

Designs and stock come from the same database the desk / store use (sale.meraboutique.in desk,
meraboutique admin): "latest" = most recently added designs, "stock" = total pieces left
across all sizes and locations. Only designs that are visible and have stock are shown.

Each design plays its reel exactly as on deals.meraboutique.in/?tab=reels (same video files,
from sale.meraboutique.in/api/media/clips). Designs with no reel get a slideshow of their photos.
Design No, price and the sizes still in stock are printed at the bottom of every clip.

Run it on a machine that stays on while streaming (your laptop with sleep turned off, or your server):
  1. Install Python 3 and ffmpeg.
  2. Set the keys (Mac/Linux: export NAME='value'   Windows: set NAME=value):
       ADMIN_PASSWORD  your admin password (same one you use on the admin panel)
       FB_KEY          your Facebook stream key (FB-...)
       IG_URL, IG_KEY  the Instagram "Stream URL" and "Stream key"
  3. python3 live_stream.py              (Windows: py live_stream.py)
  4. Click "Go live" in Facebook Live Producer and Instagram once the preview shows the video.

Check without going live:  python3 live_stream.py --dry-run   (writes preview.mp4, ~3 minutes)
Stop early: press Ctrl+C in that window.
"""
import argparse, json, os, re, shutil, subprocess, sys, urllib.request

SUPABASE_URL = "https://aqadiwwtahegfevslygc.supabase.co"
CLIPS_URL = "https://sale.meraboutique.in/api/media/clips"   # same list the Reels tab uses
W, H, FPS = 720, 1280, 30          # vertical 9:16, accepted by both Instagram and Facebook
SIZE_LETTERS = {"36": "S", "38": "M", "40": "L", "42": "XL", "44": "XXL", "46": "3XL", "48": "4XL", "50": "5XL"}


def log(*a):
    print(*a, flush=True)


def find_font():
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/Library/Fonts/Arial Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "C:/Windows/Fonts/arialbd.ttf"):
        if os.path.exists(f):
            return f
    sys.exit("No font found for the design labels. Linux: sudo apt-get install -y fonts-dejavu-core")


# ---------- reading designs + stock from the desk database ----------
def load_designs(password, mock=None):
    if mock:
        data = json.load(open(mock, encoding="utf-8"))
    else:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/functions/v1/inventory-api",
            data=json.dumps({"action": "stock_overview", "admin_password": password}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            body = json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            sys.exit(f"Desk refused the request ({e.code}). Check ADMIN_PASSWORD. {e.read()[:200]!r}")
        if body.get("error"):
            sys.exit("Desk error: " + str(body["error"]))
        data = body["data"]

    stock = {}       # product_id -> {size: qty}
    for r in data["inventory"]:
        q = int(r.get("stock_count") or 0)
        if q > 0:
            stock.setdefault(r["product_id"], {})[r["size"]] = q
    designs = []
    for p in data["products"]:
        if not p.get("design_no") or not p.get("image"):
            continue
        if p.get("is_visible") is False or (p.get("status") or "active") not in ("active", "published", ""):
            continue
        sizes = stock.get(p["id"], {})
        total = sum(sizes.values())
        if total <= 0:
            continue
        price = p.get("sale_price") or p.get("price") or ""
        designs.append({
            "design": str(p["design_no"]),
            "price": f"{float(price):g}" if price != "" else "",
            "sizes": ", ".join(SIZE_LETTERS.get(s, s) for s in sorted(sizes, key=lambda s: (len(s), s))),
            "images": [p["image"]] + [i for i in (p.get("images") or []) if i and i != p["image"]],
            "created": p.get("created_at") or "",
            "stock": total,
        })
    return designs


# ---------- reels ----------
def load_reels(mock=None):
    try:
        j = json.load(open(mock)) if mock else json.load(urllib.request.urlopen(CLIPS_URL, timeout=60))
        return {k.upper(): v for k, v in (j.get("clips") or {}).items()}
    except Exception as e:
        log("Could not load the reels list, using photos only:", e)
        return {}


def reel_for(reels, design):
    """Same matching as the Reels tab (tolerates the hyphen in codes like 2152-B)."""
    up = design.upper()
    if up in reels:
        return reels[up]
    m = re.match(r"^([A-Z]*)-?(\d.*)$", up)
    if m:
        for c in (f"{m.group(1)}-{m.group(2)}", f"{m.group(1)}{m.group(2)}"):
            if c in reels:
                return reels[c]
    return None


# ---------- making clips ----------
def download(url, dest):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        with open(dest, "rb") as f:
            if f.read(15).lower().startswith((b"<!doctype", b"<html")):
                return None
        return dest
    except Exception as e:
        log("   photo download failed:", url[:80], e)
        return None


def make_clip(p, work, font, per_photo, max_photos, max_reel):
    """Slideshow of the design's photos, same encoding for every clip so they join without gaps."""
    key = re.sub(r"[^A-Za-z0-9_-]", "_", p["design"])
    out = os.path.join(work, f"clip_{key}.mp4")
    if os.path.exists(out) and os.path.getsize(out) > 10000:
        return out
    label = f"Design {p['design']}" + (f"   Rs {p['price']}" if p["price"] else "")
    sizes = f"Sizes: {p['sizes']}"
    fit = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
           f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS},format=yuv420p")
    # Labels go in small text files next to a copy of the font, and ffmpeg runs inside the work
    # folder, so the filter only ever sees plain names (no "C:" or ":" for Windows to trip on).
    with open(os.path.join(work, f"t1_{key}.txt"), "w", encoding="utf-8") as f:
        f.write(label)
    with open(os.path.join(work, f"t2_{key}.txt"), "w", encoding="utf-8") as f:
        f.write(sizes)
    text = (f"drawbox=x=0:y=ih-230:w=iw:h=230:color=black@0.6:t=fill,"
            f"drawtext=fontfile=font.ttf:textfile=t1_{key}.txt:fontcolor=white:fontsize=52:"
            f"x=(w-text_w)/2:y=h-200,"
            f"drawtext=fontfile=font.ttf:textfile=t2_{key}.txt:fontcolor=white:fontsize=38:"
            f"x=(w-text_w)/2:y=h-120")
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-b:v", "2500k", "-maxrate", "2500k",
           "-bufsize", "5000k", "-g", str(FPS * 2), "-keyint_min", str(FPS * 2), "-sc_threshold", "0",
           "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]

    if p.get("reel"):
        src = download(p["reel"], os.path.join(work, f"reel_{key}.mp4"))
        if src:
            has_audio = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                 "-of", "csv=p=0", src], capture_output=True, text=True).stdout.strip()
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", src]
            if not has_audio:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
            cmd += ["-t", str(max_reel), "-vf", fit + "," + text, "-map", "0:v:0",
                    "-map", "0:a:0" if has_audio else "1:a:0", "-shortest"] + enc + [out]
            if subprocess.run(cmd, cwd=work).returncode == 0:
                return out
            log(f"   reel for {p['design']} unusable, using photos")

    imgs = []
    for i, url in enumerate(p["images"][:max_photos]):
        f = download(url, os.path.join(work, f"img_{key}_{i}"))
        if f:
            imgs.append(f)
    if not imgs:
        log(f"   skipping {p['design']}: no photo could be downloaded")
        return None

    cmd = ["ffmpeg", "-y", "-v", "error"]
    for f in imgs:
        cmd += ["-loop", "1", "-t", str(per_photo), "-i", f]
    cmd += ["-f", "lavfi", "-t", str(per_photo * len(imgs)), "-i", "anullsrc=r=44100:cl=stereo"]
    chain = ";".join(f"[{i}:v]{fit}[v{i}]" for i in range(len(imgs)))
    chain += ";" + "".join(f"[v{i}]" for i in range(len(imgs))) + f"concat=n={len(imgs)}:v=1:a=0,{text}[v]"
    cmd += ["-filter_complex", chain, "-map", "[v]", "-map", f"{len(imgs)}:a"] + enc + [out]
    if subprocess.run(cmd, cwd=work).returncode != 0:
        log(f"   skipping {p['design']}: ffmpeg could not make the clip")
        return None
    return out


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
    ap.add_argument("--per-photo", type=int, default=3, help="seconds per photo")
    ap.add_argument("--max-photos", type=int, default=4, help="photos per design")
    ap.add_argument("--max-reel-sec", type=int, default=60, help="cut reels longer than this")
    ap.add_argument("--photos-only", action="store_true", help="ignore reels, use photo slideshows")
    ap.add_argument("--mock-clips", help=argparse.SUPPRESS)
    ap.add_argument("--work", default=os.path.join(os.path.expanduser("~"), "live_work"))
    ap.add_argument("--mock", help=argparse.SUPPRESS)   # local JSON instead of the desk (testing)
    ap.add_argument("--dry-run", action="store_true",
                    help="no streaming; write the first ~3 minutes to preview.mp4")
    a = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} is not installed (it comes with ffmpeg).")
    font = find_font()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password and not a.mock:
        sys.exit("Set ADMIN_PASSWORD first (the admin panel password).")
    targets = []
    fb = os.environ.get("FB_KEY", "").strip()
    if fb:   # a bare Facebook key is fine: add Facebook's server address in front
        targets.append(fb if fb.startswith("rtmp") else "rtmps://live-api-s.facebook.com:443/rtmp/" + fb)
    ig = os.environ.get("IG_KEY", "").strip()
    if ig:
        if not ig.startswith("rtmp"):
            ig_url = os.environ.get("IG_URL", "").strip()
            if not ig_url.startswith("rtmp"):
                sys.exit('Instagram needs its Stream URL too. Copy "Stream URL" from the Instagram Live page and run:\n'
                         '  $env:IG_URL="rtmps://...the Stream URL..."\n'
                         'Or remove Instagram for now with:  $env:IG_KEY=""')
            ig = ig_url.rstrip("/") + "/" + ig
        targets.append(ig)
    if not a.dry_run and not targets:
        sys.exit("Set FB_KEY and/or IG_KEY (full rtmps://... address including the stream key).")
    os.makedirs(a.work, exist_ok=True)
    shutil.copyfile(font, os.path.join(a.work, "font.ttf"))

    designs = load_designs(password, a.mock)
    if not designs:
        sys.exit("No visible designs with stock found.")
    reels = {} if a.photos_only else load_reels(a.mock_clips)
    for d in designs:
        d["reel"] = reel_for(reels, d["design"])
    log(f"{len(designs)} designs in stock, {sum(1 for d in designs if d['reel'])} with a reel")

    latest = sorted(designs, key=lambda d: d["created"], reverse=True)[:a.block]
    by_stock = sorted(designs, key=lambda d: d["stock"], reverse=True)
    stock_blocks = [by_stock[i:i + a.block] for i in range(0, len(by_stock), a.block)]
    log("Latest:", ", ".join(d["design"] for d in latest))
    for i, b in enumerate(stock_blocks[:5], 1):
        log(f"Stock block {i}:", ", ".join(f"{d['design']}({d['stock']})" for d in b))

    # how many stock blocks fit in the time, so we only prepare clips we will use
    est = 12 * a.block            # rough seconds per block
    blocks_needed = int(a.hours * 3600 / est) + 2 if not a.dry_run else 2
    use = {d["design"]: d for d in latest}
    for b in stock_blocks[:blocks_needed // 2 + 1]:
        use.update({d["design"]: d for d in b})
    log(f"Preparing {len(use)} clips (cached in {a.work})...")
    clip = {}
    for n, d in enumerate(use.values(), 1):
        log(f" {n}/{len(use)}  {d['design']}")
        c = make_clip(d, a.work, font, a.per_photo, a.max_photos, a.max_reel_sec)
        if c:
            clip[d["design"]] = (c, duration(c))

    target = a.hours * 3600 if not a.dry_run else 180
    order, total, n = [], 0.0, 0
    while total < target:
        block = latest if n % 2 == 0 else stock_blocks[(n // 2) % len(stock_blocks)]
        for d in block:
            if d["design"] in clip and total < target:
                order.append(clip[d["design"]][0])
                total += clip[d["design"]][1]
        n += 1
        if n > 4 and not order:
            sys.exit("No clips could be made; check the photos open in a browser.")
    playlist = os.path.join(a.work, "playlist.txt")
    with open(playlist, "w", encoding="utf-8") as f:
        for c in order:
            f.write("file '" + c.replace("\\", "/").replace("'", "'\\''") + "'\n")
    log(f"Running order: {len(order)} clips, {total / 60:.0f} minutes, {n} blocks")

    if a.dry_run:
        out = os.path.join(os.getcwd(), "preview.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", playlist, "-c", "copy", out], check=True)
        log("Dry run done ->", out)
        return
    # one independent sender per platform: if Instagram drops, Facebook keeps going (and vice versa)
    log(f"GOING LIVE to {len(targets)} destination(s) for {total / 3600:.2f} hours")
    procs = [subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "warning", "-re",
                               "-f", "concat", "-safe", "0", "-i", playlist,
                               "-map", "0:v", "-map", "0:a", "-c", "copy", "-f", "flv", t])
             for t in targets]
    try:
        codes = [p.wait() for p in procs]
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()
        codes = [p.wait() for p in procs]
    log("Stream ended, exit codes", codes)


if __name__ == "__main__":
    main()
