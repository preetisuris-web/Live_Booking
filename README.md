# Live Booking - GitHub Pages Ready

This package contains a mobile-first booking page that pulls products from a Google Sheet and opens WhatsApp with prefilled booking messages. It also supports video thumbnails and popup playback.

Files
- index.html  (main booking page)
- sample_products.csv  (example CSV you can import into Google Sheets)

How to use
1. Open your Google Sheet (it should have a sheet named `Products`) with columns in this order:
   Image Link,Design No,Price,Available Sizes,Position,Video Link
2. Make the sheet **visible to anyone with the link** (Share → Anyone with the link → Viewer).
3. If your sheet is published as JSON (Google's gviz), the page will fetch it using the Sheet ID embedded in index.html.
4. If you need to change the sheet, open `index.html` and update the SHEET_ID constant near the top.

How to host on GitHub Pages
1. Create a new GitHub repository (or use your existing `Live_Booking`).
2. Upload `index.html` and `sample_products.csv` to the repo root.
3. Commit and push.
4. Go to Settings → Pages → Source and choose the `main` branch and `/ (root)`.
5. Wait ~1 minute and open: https://<your-username>.github.io/<repo-name>/

Notes
- Use direct image links (or Drive links in the format `https://drive.google.com/uc?export=view&id=FILE_ID`).
- Videos can be YouTube links (a YouTube ID detection is included) or direct MP4 links.
- The page sorts products by the Position column.
