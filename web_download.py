"""Download manager: background jobs, zip creation, SSE progress, cleanup."""

import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from queue import Queue
from typing import Optional

import flickr_downloader as core


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    ZIPPING = "zipping"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DownloadJob:
    job_id: str
    status: JobStatus = JobStatus.PENDING
    progress_queue: Queue = field(default_factory=Queue)
    zip_path: Optional[str] = None
    temp_dir: Optional[str] = None
    error: Optional[str] = None
    downloader: Optional[core.FlickrDownloader] = None
    created_at: float = field(default_factory=time.time)
    photo_count: int = 0
    downloaded_count: int = 0


class DownloadManager:
    """Manages download jobs with background threads."""

    def __init__(self, max_concurrent: int = 2):
        self._jobs: dict[str, DownloadJob] = {}
        self._lock = threading.Lock()
        self._max_concurrent = max_concurrent
        cleanup = threading.Thread(target=self._cleanup_loop, daemon=True)
        cleanup.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_job(self, api_key: str, api_secret: str,
                   tab_type: str, params: dict) -> str:
        """Start a new download job in a background thread. Returns job_id."""
        job_id = uuid.uuid4().hex[:12]
        job = DownloadJob(job_id=job_id)

        with self._lock:
            active = sum(
                1 for j in self._jobs.values()
                if j.status in (JobStatus.RUNNING, JobStatus.ZIPPING)
            )
            if active >= self._max_concurrent:
                raise RuntimeError(
                    "Too many concurrent downloads. Please wait.")
            self._jobs[job_id] = job

        thread = threading.Thread(
            target=self._run_job,
            args=(job, api_key, api_secret, tab_type, params),
            daemon=True,
        )
        thread.start()
        return job_id

    def get_job(self, job_id: str) -> Optional[DownloadJob]:
        return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job and job.downloader:
            job.downloader.cancel()
            job.status = JobStatus.CANCELLED
            job.progress_queue.put({"type": "cancelled"})

    def get_zip_path(self, job_id: str) -> Optional[str]:
        job = self._jobs.get(job_id)
        if job and job.zip_path and os.path.exists(job.zip_path):
            return job.zip_path
        return None

    # ------------------------------------------------------------------
    # Background job
    # ------------------------------------------------------------------

    def _run_job(self, job: DownloadJob, api_key: str, api_secret: str,
                 tab_type: str, params: dict) -> None:
        temp_dir = tempfile.mkdtemp(prefix="flickr_dl_")
        job.temp_dir = temp_dir

        try:
            dl = core.FlickrDownloader(api_key, api_secret)
            job.downloader = dl
            job.status = JobStatus.RUNNING

            def progress_cb(current, total):
                job.downloaded_count = current
                job.photo_count = total
                job.progress_queue.put({
                    "type": "progress",
                    "current": current,
                    "total": total,
                })

            def log_cb(msg):
                job.progress_queue.put({"type": "log", "message": msg})

            dl.set_callbacks(progress_cb=progress_cb, log_cb=log_cb)

            # Fetch photos
            photos = self._fetch_photos(dl, tab_type, params, log_cb)

            if dl.is_cancelled:
                job.status = JobStatus.CANCELLED
                job.progress_queue.put({"type": "cancelled"})
                return

            if not photos:
                job.status = JobStatus.COMPLETE
                job.progress_queue.put({
                    "type": "complete",
                    "message": "No photos found.",
                    "file_ready": False,
                })
                return

            # Download to temp dir
            downloaded, skipped, failed = dl.download_photos(
                photos, temp_dir,
                size_key=params.get("size_key", "url_l"),
                embed_metadata=params.get("embed_metadata", True),
                filename_template=params.get(
                    "filename_template", "{title}_{id}"),
            )

            if dl.is_cancelled:
                job.status = JobStatus.CANCELLED
                job.progress_queue.put({"type": "cancelled"})
                return

            # Zip
            job.status = JobStatus.ZIPPING
            job.progress_queue.put({"type": "zipping"})

            zip_path = os.path.join(
                tempfile.gettempdir(), f"flickr_{job.job_id}.zip")
            with zipfile.ZipFile(zip_path, "w",
                                 zipfile.ZIP_DEFLATED) as zf:
                for fname in os.listdir(temp_dir):
                    fpath = os.path.join(temp_dir, fname)
                    if os.path.isfile(fpath):
                        zf.write(fpath, fname)

            job.zip_path = zip_path
            job.status = JobStatus.COMPLETE
            job.progress_queue.put({
                "type": "complete",
                "message": (f"Downloaded {downloaded}, "
                            f"skipped {skipped}, failed {failed}."),
                "file_ready": True,
                "job_id": job.job_id,
            })

        except core.CancelledError:
            job.status = JobStatus.CANCELLED
            job.progress_queue.put({"type": "cancelled"})
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.progress_queue.put({"type": "error", "message": str(e)})
        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def _fetch_photos(dl, tab_type, params, log_cb):
        """Call the appropriate core fetch method."""
        if tab_type == "interestingness":
            photos = dl.fetch_interestingness(
                params["date"], params["count"])
            if params.get("user_id"):
                nsid = params["user_id"]
                photos = [p for p in photos if p.get("owner") == nsid]
                log_cb(f"Filtered to {len(photos)} photos by user.")
            return photos

        if tab_type == "search":
            return dl.search_photos(
                text=params.get("text", ""),
                tags=params.get("tags", ""),
                tag_mode=params.get("tag_mode", "any"),
                sort=params.get("sort", "relevance"),
                license_ids=params.get("license_ids", ""),
                count=params.get("count", 100),
                user_id=params.get("user_id", ""),
            )

        if tab_type == "user_photostream":
            return dl.fetch_user_photos(
                params["user_nsid"], params["count"])

        if tab_type == "album":
            log_cb(f"Downloading album: {params.get('album_title', '')}")
            return dl.fetch_album_photos(
                params["user_nsid"], params["album_id"])

        return []

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup_loop(self) -> None:
        """Remove expired jobs and their zip files every 60 s."""
        while True:
            time.sleep(60)
            cutoff = time.time() - 600  # 10 minutes
            with self._lock:
                expired = [
                    jid for jid, j in self._jobs.items()
                    if j.created_at < cutoff
                    and j.status in (JobStatus.COMPLETE,
                                     JobStatus.FAILED,
                                     JobStatus.CANCELLED)
                ]
                for jid in expired:
                    job = self._jobs.pop(jid)
                    if job.zip_path and os.path.exists(job.zip_path):
                        try:
                            os.remove(job.zip_path)
                        except OSError:
                            pass
