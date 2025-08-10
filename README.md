# Booking Page with WhatsApp + Video Preview

## How to Use
1. Go to your Google Sheet and publish it to the web as CSV.
2. Copy the CSV link and replace the `CSV_URL` in `index.html`.
3. Upload these files to a **new GitHub repository**.
4. In your repository, go to **Settings > Pages > Source** and select `main` branch, `/ (root)` folder.
5. Your booking page will be live at:  
   `https://<your-username>.github.io/<repo-name>`

## CSV Format
Your sheet should have columns in this order:
```
Image Link,Design No.,Price,Available Sizes,Position,Video Link
```

- **Image Link** → Direct link to product image
- **Design No.** → Unique product ID
- **Price** → Price in ₹
- **Available Sizes** → Comma-separated sizes
- **Position** → Display order (1 = top)
- **Video Link** → (Optional) YouTube/Vimeo/MP4 link
