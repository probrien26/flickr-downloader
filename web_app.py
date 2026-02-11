#!/usr/bin/env python3
"""Flask web application for the Flickr Photo Downloader."""

import json
import os
import sys
from datetime import datetime, timedelta
from functools import wraps
from queue import Empty

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, Response, send_file, stream_with_context,
)
from dotenv import load_dotenv
import requests as http_requests

# Ensure core module is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

import flickr_downloader as core
from web_auth import (
    check_password, check_totp, is_totp_configured,
    generate_totp_secret, generate_totp_qr,
    is_rate_limited, record_failed_attempt, reset_attempts,
)
from web_download import DownloadManager

# ====================================================================
# App setup
# ====================================================================

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32).hex())
app.permanent_session_lifetime = timedelta(hours=8)

download_manager = DownloadManager()


def _flickr_keys():
    """Return (api_key, api_secret) from environment."""
    return (
        os.environ.get("FLICKR_API_KEY", ""),
        os.environ.get("FLICKR_API_SECRET", ""),
    )


# ====================================================================
# Auth decorator
# ====================================================================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ====================================================================
# Auth routes
# ====================================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("index"))

    if request.method == "POST":
        ip = request.remote_addr
        if is_rate_limited(ip):
            flash("Too many failed attempts. Try again later.", "error")
            return render_template("login.html",
                                   totp_configured=is_totp_configured())

        password = request.form.get("password", "")
        if check_password(password):
            reset_attempts(ip)
            session["password_ok"] = True
            if is_totp_configured():
                return redirect(url_for("totp_verify"))
            # No TOTP configured — grant full access
            session["authenticated"] = True
            session.permanent = True
            return redirect(url_for("index"))
        else:
            record_failed_attempt(ip)
            flash("Invalid password.", "error")

    return render_template("login.html",
                           totp_configured=is_totp_configured())


@app.route("/totp", methods=["GET", "POST"])
def totp_verify():
    if not session.get("password_ok"):
        return redirect(url_for("login"))
    if session.get("authenticated"):
        return redirect(url_for("index"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        if check_totp(code):
            session["authenticated"] = True
            session.permanent = True
            session.pop("password_ok", None)
            return redirect(url_for("index"))
        else:
            flash("Invalid code. Please try again.", "error")

    return render_template("totp_verify.html")


@app.route("/totp-setup", methods=["GET", "POST"])
def totp_setup():
    # Only allow setup when TOTP is not yet configured
    if is_totp_configured():
        flash("2FA is already configured.", "info")
        return redirect(url_for("login"))

    # Must know the admin password first
    if not session.get("password_ok"):
        flash("Please log in first.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        secret = request.form.get("secret", "")
        code = request.form.get("code", "").strip()

        import pyotp
        totp = pyotp.TOTP(secret)
        if totp.verify(code, valid_window=1):
            # Temporarily set the env var for the current process
            os.environ["TOTP_SECRET"] = secret
            # Inform the user to persist it
            flash("2FA setup complete! Add TOTP_SECRET to your Render "
                  "environment variables to persist across deploys.",
                  "success")
            session["authenticated"] = True
            session.permanent = True
            session.pop("password_ok", None)
            return render_template("totp_setup.html",
                                   qr_data_uri="", secret="",
                                   setup_complete=True,
                                   confirmed_secret=secret)
        else:
            flash("Invalid code. Please try again.", "error")

    secret = session.get("setup_secret")
    if not secret:
        secret = generate_totp_secret()
        session["setup_secret"] = secret

    qr = generate_totp_qr(secret)
    return render_template("totp_setup.html",
                           qr_data_uri=qr, secret=secret,
                           setup_complete=False,
                           confirmed_secret="")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ====================================================================
# Main page
# ====================================================================

@app.route("/")
@login_required
def index():
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return render_template(
        "index.html",
        yesterday=yesterday,
        photo_sizes=core.PHOTO_SIZES,
        sort_options=core.SORT_OPTIONS,
        license_map=core.LICENSE_MAP,
    )


# ====================================================================
# API routes — search / preview
# ====================================================================

@app.route("/api/search", methods=["POST"])
@login_required
def api_search():
    data = request.get_json(silent=True) or {}
    api_key, api_secret = _flickr_keys()
    if not api_key or not api_secret:
        return jsonify(error="Flickr API credentials not configured."), 500

    try:
        dl = core.FlickrDownloader(api_key, api_secret)
        photos = dl.search_photos(
            text=data.get("text", ""),
            tags=data.get("tags", ""),
            tag_mode=data.get("tag_mode", "any"),
            sort=data.get("sort", "relevance"),
            license_ids=data.get("license_ids", ""),
            count=min(int(data.get("count", 100)), 500),
            user_id=data.get("user_id", ""),
        )
        total = len(photos)
        preview = []
        for p in photos[:50]:
            title = p.get("title", "")
            if isinstance(title, dict):
                title = title.get("_content", "")
            preview.append({
                "id": p.get("id", ""),
                "title": title,
                "owner": p.get("ownername", "") or p.get("owner", ""),
                "date_taken": p.get("datetaken", ""),
                "thumb_url": p.get("url_sq", ""),
            })
        return jsonify(total=total, preview=preview)
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/interestingness", methods=["POST"])
@login_required
def api_interestingness():
    data = request.get_json(silent=True) or {}
    api_key, api_secret = _flickr_keys()
    if not api_key or not api_secret:
        return jsonify(error="Flickr API credentials not configured."), 500

    try:
        dl = core.FlickrDownloader(api_key, api_secret)
        date_str = data.get("date", "")
        count = min(int(data.get("count", 500)), 500)
        photos = dl.fetch_interestingness(date_str, count)
        return jsonify(total=len(photos))
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/resolve-user", methods=["POST"])
@login_required
def api_resolve_user():
    data = request.get_json(silent=True) or {}
    api_key, api_secret = _flickr_keys()
    if not api_key or not api_secret:
        return jsonify(error="Flickr API credentials not configured."), 500

    username = data.get("username", "").strip()
    if not username:
        return jsonify(error="Username is required.")

    try:
        dl = core.FlickrDownloader(api_key, api_secret)
        nsid, uname = dl.resolve_user(username)
        albums = dl.fetch_user_albums(nsid)
        album_list = [{"id": a["id"], "title": a["title"],
                       "photos": a["photos"]} for a in albums]
        return jsonify(nsid=nsid, username=uname, albums=album_list)
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/preview-thumb")
@login_required
def proxy_thumb():
    """Proxy Flickr thumbnail to avoid CORS issues."""
    url = request.args.get("url", "")
    if not url or "staticflickr.com" not in url:
        return "", 400
    try:
        resp = http_requests.get(url, timeout=10)
        return Response(
            resp.content,
            mimetype=resp.headers.get("Content-Type", "image/jpeg"),
        )
    except Exception:
        return "", 502


# ====================================================================
# API routes — download
# ====================================================================

@app.route("/api/download/start", methods=["POST"])
@login_required
def api_download_start():
    data = request.get_json(silent=True) or {}
    api_key, api_secret = _flickr_keys()
    if not api_key or not api_secret:
        return jsonify(error="Flickr API credentials not configured."), 500

    tab_type = data.get("tab_type", "")
    if not tab_type:
        return jsonify(error="No tab type specified."), 400

    params = {
        "size_key": data.get("size_key", "url_l"),
        "embed_metadata": data.get("embed_metadata", True),
        "filename_template": data.get("filename_template", "{title}_{id}"),
    }

    # Tab-specific params
    if tab_type == "interestingness":
        params["date"] = data.get("date", "")
        params["count"] = min(int(data.get("count", 500)), 500)
        if data.get("user_id"):
            params["user_id"] = data["user_id"]

    elif tab_type == "search":
        params["text"] = data.get("text", "")
        params["tags"] = data.get("tags", "")
        params["tag_mode"] = data.get("tag_mode", "any")
        params["sort"] = data.get("sort", "relevance")
        params["license_ids"] = data.get("license_ids", "")
        params["count"] = min(int(data.get("count", 100)), 4000)
        if data.get("user_id"):
            params["user_id"] = data["user_id"]

    elif tab_type == "user_photostream":
        params["user_nsid"] = data.get("user_nsid", "")
        params["count"] = min(int(data.get("count", 500)), 5000)

    elif tab_type == "album":
        params["user_nsid"] = data.get("user_nsid", "")
        params["album_id"] = data.get("album_id", "")
        params["album_title"] = data.get("album_title", "")

    else:
        return jsonify(error="Invalid tab type."), 400

    try:
        job_id = download_manager.create_job(
            api_key, api_secret, tab_type, params)
        return jsonify(job_id=job_id)
    except RuntimeError as e:
        return jsonify(error=str(e)), 429


@app.route("/api/download/progress/<job_id>")
@login_required
def api_download_progress(job_id):
    job = download_manager.get_job(job_id)
    if not job:
        return jsonify(error="Job not found."), 404

    def generate():
        while True:
            try:
                event = job.progress_queue.get(timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("complete", "error", "cancelled"):
                    break
            except Empty:
                yield ": keepalive\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/download/file/<job_id>")
@login_required
def api_download_file(job_id):
    zip_path = download_manager.get_zip_path(job_id)
    if not zip_path:
        return jsonify(error="File not found or expired."), 404
    return send_file(
        zip_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"flickr_photos_{job_id}.zip",
    )


@app.route("/api/download/cancel/<job_id>", methods=["POST"])
@login_required
def api_download_cancel(job_id):
    download_manager.cancel_job(job_id)
    return jsonify(ok=True)


# ====================================================================
# Entry point
# ====================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
