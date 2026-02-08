#!/usr/bin/env python3
"""Core logic for the Flickr Photo Downloader application."""

import os
import re
import time

import flickrapi
import requests
from dotenv import load_dotenv

# Metadata support: prefer pyexiv2, fall back to piexif
_HAS_PYEXIV2 = False
_HAS_PIEXIF = False
try:
    import pyexiv2
    _HAS_PYEXIV2 = True
except ImportError:
    pass
if not _HAS_PYEXIV2:
    try:
        import piexif
        _HAS_PIEXIF = True
    except ImportError:
        pass

# Photo size labels mapped to flickrapi extras suffix keys
PHOTO_SIZES = {
    "Square 75": "url_sq",
    "Thumbnail": "url_t",
    "Small 240": "url_s",
    "Small 320": "url_n",
    "Medium 500": "url_m",
    "Medium 640": "url_z",
    "Medium 800": "url_c",
    "Large 1024": "url_l",
    "Large 1600": "url_h",
    "Original": "url_o",
}

# All extras we request so photo dicts include URLs and metadata
_EXTRAS = (
    "url_sq,url_t,url_s,url_n,url_m,url_z,url_c,url_l,url_h,url_o,"
    "description,tags,owner_name,date_taken"
)

# Characters not allowed in Windows filenames
_RESERVED_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Flickr Creative Commons license map
LICENSE_MAP = {
    "All Rights Reserved": "0",
    "CC BY-NC-SA 2.0": "1",
    "CC BY-NC 2.0": "2",
    "CC BY-NC-ND 2.0": "3",
    "CC BY 2.0": "4",
    "CC BY-SA 2.0": "5",
    "CC BY-ND 2.0": "6",
    "Public Domain (CC0)": "9",
    "Public Domain Mark": "10",
}

SORT_OPTIONS = {
    "Relevance": "relevance",
    "Date Posted (Newest)": "date-posted-desc",
    "Date Posted (Oldest)": "date-posted-asc",
    "Date Taken (Newest)": "date-taken-desc",
    "Date Taken (Oldest)": "date-taken-asc",
    "Interestingness (Highest)": "interestingness-desc",
    "Interestingness (Lowest)": "interestingness-asc",
}


class FlickrDownloader:
    """Handles all Flickr API calls and photo downloading."""

    def __init__(self, api_key, api_secret):
        self.flickr = flickrapi.FlickrAPI(
            api_key, api_secret, format="parsed-json"
        )
        self._cancelled = False
        self._progress_cb = None
        self._log_cb = None

    def set_callbacks(self, progress_cb=None, log_cb=None):
        """Set callbacks for progress updates and log messages."""
        self._progress_cb = progress_cb
        self._log_cb = log_cb

    def cancel(self):
        self._cancelled = True

    def reset_cancel(self):
        self._cancelled = False

    @property
    def is_cancelled(self):
        return self._cancelled

    def _log(self, msg):
        if self._log_cb:
            self._log_cb(msg)

    def _progress(self, current, total):
        if self._progress_cb:
            self._progress_cb(current, total)

    def _api_call(self, func, **kwargs):
        """Call a Flickr API method with exponential backoff (3 attempts)."""
        max_retries = 3
        for attempt in range(max_retries):
            if self._cancelled:
                raise CancelledError("Operation cancelled")
            try:
                return func(**kwargs)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                wait = 2 ** attempt
                self._log(f"  API error: {e}. Retrying in {wait}s...")
                time.sleep(wait)

    # --- Fetch methods ---

    def fetch_interestingness(self, date_str, count):
        """Fetch photos from Flickr's Interestingness/Explore feed.

        Args:
            date_str: Date in YYYY-MM-DD format.
            count: Number of photos to fetch (max 500).

        Returns:
            List of photo dicts with URL extras.
        """
        photos = []
        per_page = min(count, 500)
        total_pages = (count + per_page - 1) // per_page

        for page in range(1, total_pages + 1):
            if self._cancelled:
                break
            self._log(f"Fetching interestingness page {page}/{total_pages}...")
            resp = self._api_call(
                self.flickr.interestingness.getList,
                date=date_str,
                extras=_EXTRAS,
                per_page=per_page,
                page=page,
            )
            batch = resp["photos"]["photo"]
            if not batch:
                break
            photos.extend(batch)
            if page >= int(resp["photos"]["pages"]):
                break

        photos = photos[:count]
        self._log(f"Found {len(photos)} interestingness photos.")
        return photos

    def search_photos(self, text="", tags="", tag_mode="any",
                      sort="relevance", license_ids="", count=100,
                      user_id=""):
        """Search Flickr for photos matching criteria.

        Args:
            text: Free-text search query.
            tags: Comma-separated tags.
            tag_mode: 'any' or 'all'.
            sort: Sort order (flickr API value).
            license_ids: Comma-separated license IDs.
            count: Number of results (max 4000).
            user_id: Optional user NSID to restrict results to.

        Returns:
            List of photo dicts with URL extras.
        """
        photos = []
        per_page = min(count, 500)
        total_pages = (count + per_page - 1) // per_page

        kwargs = {
            "extras": _EXTRAS,
            "per_page": per_page,
            "sort": sort,
            "safe_search": 1,
        }
        if text:
            kwargs["text"] = text
        if tags:
            kwargs["tags"] = tags
            kwargs["tag_mode"] = tag_mode
        if license_ids:
            kwargs["license"] = license_ids
        if user_id:
            kwargs["user_id"] = user_id

        for page in range(1, total_pages + 1):
            if self._cancelled:
                break
            self._log(f"Fetching search results page {page}/{total_pages}...")
            resp = self._api_call(self.flickr.photos.search, page=page, **kwargs)
            batch = resp["photos"]["photo"]
            if not batch:
                break
            photos.extend(batch)
            if page >= int(resp["photos"]["pages"]):
                break

        photos = photos[:count]
        self._log(f"Found {len(photos)} photos from search.")
        return photos

    def resolve_user(self, username_or_url):
        """Resolve a Flickr username or profile URL to a user NSID.

        Args:
            username_or_url: Either a plain username or a Flickr URL.

        Returns:
            Tuple of (nsid, username).
        """
        username_or_url = username_or_url.strip()

        # Try as URL first if it looks like one
        if "/" in username_or_url or "flickr.com" in username_or_url.lower():
            url = username_or_url
            if not url.startswith("http"):
                url = "https://" + url
            try:
                resp = self._api_call(self.flickr.urls.lookupUser, url=url)
                nsid = resp["user"]["id"]
                uname = resp["user"]["username"]["_content"]
                self._log(f"Resolved URL to user: {uname} ({nsid})")
                return nsid, uname
            except Exception:
                self._log("URL lookup failed, trying as username...")

        # Try as username
        try:
            resp = self._api_call(
                self.flickr.people.findByUsername, username=username_or_url
            )
            nsid = resp["user"]["nsid"]
            uname = resp["user"]["username"]["_content"]
            self._log(f"Resolved username to: {uname} ({nsid})")
            return nsid, uname
        except Exception as e:
            raise ValueError(
                f"Could not find user '{username_or_url}': {e}"
            ) from e

    def fetch_user_albums(self, user_nsid):
        """Fetch all albums/photosets for a user.

        Args:
            user_nsid: The user's NSID.

        Returns:
            List of album dicts with 'id' and 'title' keys.
        """
        albums = []
        page = 1
        while True:
            if self._cancelled:
                break
            resp = self._api_call(
                self.flickr.photosets.getList,
                user_id=user_nsid,
                per_page=500,
                page=page,
            )
            batch = resp["photosets"]["photoset"]
            for ps in batch:
                albums.append({
                    "id": ps["id"],
                    "title": ps["title"]["_content"],
                    "photos": ps.get("photos", 0),
                })
            if page >= int(resp["photosets"]["pages"]):
                break
            page += 1

        self._log(f"Found {len(albums)} albums for user.")
        return albums

    def fetch_user_photos(self, user_nsid, count):
        """Fetch public photos from a user's photostream.

        Args:
            user_nsid: The user's NSID.
            count: Number of photos to fetch.

        Returns:
            List of photo dicts with URL extras.
        """
        photos = []
        per_page = min(count, 500)
        total_pages = (count + per_page - 1) // per_page

        for page in range(1, total_pages + 1):
            if self._cancelled:
                break
            self._log(f"Fetching user photos page {page}/{total_pages}...")
            resp = self._api_call(
                self.flickr.people.getPublicPhotos,
                user_id=user_nsid,
                extras=_EXTRAS,
                per_page=per_page,
                page=page,
            )
            batch = resp["photos"]["photo"]
            if not batch:
                break
            photos.extend(batch)
            if page >= int(resp["photos"]["pages"]):
                break

        photos = photos[:count]
        self._log(f"Found {len(photos)} photos in user's photostream.")
        return photos

    def fetch_album_photos(self, user_nsid, photoset_id):
        """Fetch all photos from a specific album/photoset.

        Args:
            user_nsid: The album owner's NSID.
            photoset_id: The photoset/album ID.

        Returns:
            List of photo dicts with URL extras.
        """
        photos = []
        page = 1
        while True:
            if self._cancelled:
                break
            self._log(f"Fetching album photos page {page}...")
            resp = self._api_call(
                self.flickr.photosets.getPhotos,
                user_id=user_nsid,
                photoset_id=photoset_id,
                extras=_EXTRAS,
                per_page=500,
                page=page,
            )
            batch = resp["photoset"]["photo"]
            if not batch:
                break
            photos.extend(batch)
            if page >= int(resp["photoset"]["pages"]):
                break
            page += 1

        self._log(f"Found {len(photos)} photos in album.")
        return photos

    # --- Download engine ---

    def _download_with_retry(self, url, max_retries=5):
        """Download a URL with retry and exponential backoff on 429 errors."""
        for attempt in range(max_retries):
            if self._cancelled:
                raise CancelledError("Operation cancelled")
            resp = requests.get(url, timeout=30, stream=True)
            if resp.status_code == 429:
                # Respect Retry-After header, otherwise use exponential backoff
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    wait = int(retry_after)
                else:
                    wait = 2 ** attempt  # 1, 2, 4, 8, 16 seconds
                if attempt < max_retries - 1:
                    self._log(f"    Rate limited (429). Waiting {wait}s before retry...")
                    time.sleep(wait)
                    continue
            resp.raise_for_status()
            return resp
        # Should not reach here, but just in case
        resp.raise_for_status()
        return resp

    def get_photo_url(self, photo, size_key):
        """Get the download URL for a photo at the requested size.

        Falls back through smaller sizes, then to getSizes API.
        """
        # Try requested size first
        if size_key in photo and photo[size_key]:
            return photo[size_key]

        # Fall back through sizes largest to smallest
        fallback_order = [
            "url_o", "url_h", "url_l", "url_c", "url_z",
            "url_m", "url_n", "url_s", "url_t", "url_sq",
        ]
        for key in fallback_order:
            if key in photo and photo[key]:
                return photo[key]

        # Last resort: call getSizes API
        try:
            resp = self._api_call(
                self.flickr.photos.getSizes, photo_id=photo["id"]
            )
            sizes = resp["sizes"]["size"]
            if sizes:
                # Return the largest available
                return sizes[-1]["source"]
        except Exception:
            pass

        return None

    def download_photos(self, photos, download_dir, size_key="url_l",
                        embed_metadata=True, filename_template="{title}_{id}"):
        """Download photos to a local directory.

        Args:
            photos: List of photo dicts from fetch methods.
            download_dir: Destination directory.
            size_key: URL extras key for desired size.
            embed_metadata: Whether to write IPTC/XMP/EXIF metadata.
            filename_template: Template with {id}, {title}, {owner} placeholders.

        Returns:
            Tuple of (downloaded_count, skipped_count, failed_count).
        """
        os.makedirs(download_dir, exist_ok=True)
        total = len(photos)
        downloaded = 0
        skipped = 0
        failed = 0

        for i, photo in enumerate(photos):
            if self._cancelled:
                self._log("Download cancelled.")
                break

            photo_id = photo["id"]
            title = photo.get("title", "") or ""
            if isinstance(title, dict):
                title = title.get("_content", "")
            owner = photo.get("ownername", "") or photo.get("owner", "")

            # Build filename
            fname = filename_template.format(
                id=photo_id,
                title=title[:100] if title else "untitled",
                owner=owner[:50] if owner else "unknown",
            )
            fname = self._sanitize_filename(fname)

            url = self.get_photo_url(photo, size_key)
            if not url:
                self._log(f"  [{i+1}/{total}] No URL for photo {photo_id}, skipping.")
                failed += 1
                self._progress(i + 1, total)
                continue

            # Determine extension from URL
            ext = self._get_extension(url)
            filepath = os.path.join(download_dir, f"{fname}{ext}")

            # Skip existing files
            if os.path.exists(filepath):
                self._log(f"  [{i+1}/{total}] Already exists: {fname}{ext}")
                skipped += 1
                self._progress(i + 1, total)
                continue

            # Download with retry on 429
            try:
                self._log(f"  [{i+1}/{total}] Downloading: {fname}{ext}")
                resp = self._download_with_retry(url)
                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if self._cancelled:
                            break
                        f.write(chunk)

                if self._cancelled:
                    # Clean up partial file
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass
                    self._log("Download cancelled.")
                    break

                # Embed metadata
                if embed_metadata and ext.lower() in (".jpg", ".jpeg"):
                    desc = photo.get("description", {})
                    if isinstance(desc, dict):
                        desc = desc.get("_content", "")
                    tags_str = photo.get("tags", "")
                    if isinstance(tags_str, dict):
                        tags_str = tags_str.get("_content", "")
                    tag_list = [t.strip() for t in tags_str.split() if t.strip()] if tags_str else []
                    self._embed_metadata(filepath, title, desc, tag_list, owner)

                downloaded += 1

            except Exception as e:
                self._log(f"  [{i+1}/{total}] Failed: {e}")
                failed += 1
                # Clean up partial file
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass

            self._progress(i + 1, total)

            # Rate limit: 1 second between downloads to avoid 429s
            if i < total - 1 and not self._cancelled:
                time.sleep(1.0)

        self._log(
            f"Download complete: {downloaded} downloaded, "
            f"{skipped} skipped, {failed} failed."
        )
        return downloaded, skipped, failed

    # --- Metadata embedding ---

    def _embed_metadata(self, filepath, title, description, tags, author):
        """Embed metadata into a JPEG file.

        Uses pyexiv2 if available (IPTC + XMP + EXIF), otherwise piexif (EXIF only).
        """
        if _HAS_PYEXIV2:
            try:
                self._embed_pyexiv2(filepath, title, description, tags, author)
                return
            except Exception as e:
                self._log(f"  pyexiv2 metadata failed: {e}")

        if _HAS_PIEXIF:
            try:
                self._embed_piexif(filepath, title, description, tags, author)
                return
            except Exception as e:
                self._log(f"  piexif metadata failed: {e}")

    def _embed_pyexiv2(self, filepath, title, description, tags, author):
        """Write IPTC, XMP, and EXIF metadata using pyexiv2."""
        with pyexiv2.Image(filepath) as img:
            # IPTC
            iptc_data = {}
            if title:
                iptc_data["Iptc.Application2.ObjectName"] = [title[:64]]
            if description:
                iptc_data["Iptc.Application2.Caption"] = [description]
            if tags:
                iptc_data["Iptc.Application2.Keywords"] = tags
            if author:
                iptc_data["Iptc.Application2.Byline"] = [author]
            if iptc_data:
                img.modify_iptc(iptc_data)

            # XMP
            xmp_data = {}
            if title:
                xmp_data["Xmp.dc.title"] = {"lang=\"x-default\"": title}
            if description:
                xmp_data["Xmp.dc.description"] = {"lang=\"x-default\"": description}
            if tags:
                xmp_data["Xmp.dc.subject"] = tags
            if author:
                xmp_data["Xmp.dc.creator"] = [author]
            if xmp_data:
                img.modify_xmp(xmp_data)

            # EXIF
            exif_data = {}
            if title or description:
                exif_data["Exif.Image.ImageDescription"] = title or description
            if author:
                exif_data["Exif.Image.Artist"] = author
            if exif_data:
                img.modify_exif(exif_data)

    def _embed_piexif(self, filepath, title, description, tags, author):
        """Write EXIF metadata using piexif (fallback)."""
        try:
            exif_dict = piexif.load(filepath)
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

        # Build a combined description
        parts = []
        if title:
            parts.append(title)
        if description:
            parts.append(description)
        if tags:
            parts.append("Tags: " + ", ".join(tags))
        combined = " | ".join(parts) if parts else ""

        if combined:
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = combined.encode("utf-8")
        if author:
            exif_dict["0th"][piexif.ImageIFD.Artist] = author.encode("utf-8")

        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, filepath)

    # --- Helpers ---

    @staticmethod
    def _sanitize_filename(name):
        """Make a string safe for use as a Windows filename."""
        # Replace reserved characters with underscore
        name = _RESERVED_CHARS.sub("_", name)
        # Remove leading/trailing spaces and dots
        name = name.strip(" .")
        # Check for reserved device names
        base = name.split(".")[0].upper()
        if base in _RESERVED_NAMES:
            name = "_" + name
        # Limit length (leave room for extension)
        if len(name) > 200:
            name = name[:200]
        return name or "photo"

    @staticmethod
    def _get_extension(url):
        """Extract file extension from a URL."""
        path = url.split("?")[0]
        _, ext = os.path.splitext(path)
        return ext.lower() if ext else ".jpg"


class CancelledError(Exception):
    """Raised when an operation is cancelled."""
    pass
