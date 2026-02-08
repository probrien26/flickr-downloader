# Flickr Photo Downloader

A desktop GUI application for browsing and downloading photos from Flickr. Search by keyword, explore daily interestingness, or download a user's photostream and albums.

## Features

- **Interestingness / Explore** - Download photos from Flickr's daily Explore feed by date
- **Search** - Find photos by keywords, tags, sort order, and license type
- **User / Album** - Download a user's photostream or specific albums
- **Search Preview** - Thumbnail grid showing up to 50 results before committing to a full download
- **User Filtering** - Optionally filter search and interestingness results to a specific user
- **Metadata Embedding** - Writes title, description, tags, and author into JPEG EXIF/IPTC/XMP
- **Configurable Downloads** - Choose photo size, filename template, and download folder
- **Settings Persistence** - All fields are saved and restored between sessions

## Requirements

- Python 3.10+
- Flickr API key and secret ([get one here](https://www.flickr.com/services/apps/create/))

## Setup

1. Clone the repository:
   ```
   git clone https://github.com/probrien26/flickr-downloader.git
   cd flickr-downloader
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Set up your API credentials using one of these methods:
   - **Option A:** Copy `.env.example` to `.env` and fill in your keys:
     ```
     FLICKR_API_KEY=your_api_key_here
     FLICKR_API_SECRET=your_api_secret_here
     ```
   - **Option B:** Enter them directly in the GUI's credential fields (they'll be saved to `settings.json`)

## Usage

Run the application:
```
python flickr_downloader_gui.py
```

### Tabs

- **Interestingness** - Pick a date and count, optionally filter by username
- **Search** - Enter keywords and/or tags, adjust sort/license/count, optionally filter by username. Click **Preview** to see a thumbnail grid before downloading.
- **User / Album** - Enter a Flickr username or profile URL, click **Look Up**, then choose photostream or a specific album

### Download Options

- **Save to** - Destination folder for downloaded photos
- **Photo size** - From 75px square up to original size
- **Embed metadata** - Write photo title, tags, description, and author into JPEG files
- **Filename** - Template using `{id}`, `{title}`, and `{owner}` placeholders

## Building an Executable

To create a standalone `.exe` with PyInstaller:
```
pip install pyinstaller
pyinstaller --onefile --windowed --icon=flickr_icon.ico --name FlickrDownloader flickr_downloader_gui.py
```

The executable will be in the `dist/` folder.

## License

This project is provided as-is for personal use.
