/* Flickr Photo Downloader — Web UI JavaScript */

let userNsid = null;
let userAlbums = [];
let currentJobId = null;
let eventSource = null;

// ====================================================================
// Tabs
// ====================================================================

document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        const tabId = 'tab-' + btn.dataset.tab;
        document.getElementById(tabId).classList.add('active');
    });
});

// ====================================================================
// User Lookup
// ====================================================================

async function lookupUser() {
    const input = document.getElementById('user-input').value.trim();
    const statusEl = document.getElementById('user-status');
    const lookupBtn = document.getElementById('lookup-btn');

    if (!input) {
        userNsid = null;
        userAlbums = [];
        document.getElementById('album-select').innerHTML = '';
        document.getElementById('album-select').disabled = true;
        statusEl.textContent = '(optional \u2013 filter by user)';
        return;
    }

    lookupBtn.disabled = true;
    statusEl.textContent = 'Looking up user...';

    try {
        const resp = await fetch('/api/resolve-user', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username: input}),
        });
        const data = await resp.json();
        if (data.error) {
            statusEl.textContent = 'Error: ' + data.error;
            return;
        }
        userNsid = data.nsid;
        userAlbums = data.albums;
        statusEl.textContent = `User: ${data.username} (${data.nsid})`;

        const select = document.getElementById('album-select');
        select.innerHTML = '';
        data.albums.forEach((a, i) => {
            const opt = document.createElement('option');
            opt.value = i;
            opt.textContent = `${a.title} (${a.photos} photos)`;
            select.appendChild(opt);
        });
    } catch (e) {
        statusEl.textContent = 'Error: ' + e.message;
    } finally {
        lookupBtn.disabled = false;
    }
}

// ====================================================================
// User / Album mode toggle
// ====================================================================

function onUserModeChange() {
    const mode = document.querySelector('input[name="user-mode"]:checked').value;
    document.getElementById('album-select').disabled = (mode !== 'album');
    document.getElementById('user-count').disabled = (mode === 'album');
}

// ====================================================================
// Preview
// ====================================================================

async function startPreview() {
    const btn = document.getElementById('preview-btn');
    const statusEl = document.getElementById('preview-status');
    const grid = document.getElementById('preview-grid');

    const text = document.getElementById('search-text').value.trim();
    const tags = document.getElementById('search-tags').value.trim();
    if (!text && !tags) {
        alert('Enter keywords and/or tags to search.');
        return;
    }

    btn.disabled = true;
    statusEl.textContent = 'Searching...';
    grid.innerHTML = '';

    try {
        const resp = await fetch('/api/search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                text: text,
                tags: tags,
                tag_mode: document.querySelector('input[name="tag-mode"]:checked').value,
                sort: document.getElementById('sort').value,
                license_ids: document.getElementById('license').value,
                count: parseInt(document.getElementById('search-count').value) || 100,
                user_id: userNsid || '',
            }),
        });
        const data = await resp.json();

        if (data.error) {
            statusEl.textContent = 'Error: ' + data.error;
            return;
        }

        if (!data.preview.length) {
            statusEl.textContent = 'No photos found.';
            return;
        }

        data.preview.forEach(photo => {
            if (!photo.thumb_url) return;
            const cell = document.createElement('div');
            cell.className = 'thumb-cell';
            cell.title = `${photo.title}\nBy: ${photo.owner}${photo.date_taken ? '\nDate: ' + photo.date_taken : ''}`;

            const img = document.createElement('img');
            img.src = '/api/preview-thumb?url=' + encodeURIComponent(photo.thumb_url);
            img.alt = photo.title;
            img.loading = 'lazy';
            cell.appendChild(img);

            const title = document.createElement('div');
            title.className = 'title';
            title.textContent = photo.title.length > 15
                ? photo.title.substring(0, 12) + '...'
                : photo.title;
            cell.appendChild(title);

            grid.appendChild(cell);
        });

        const total = data.total.toLocaleString();
        statusEl.textContent = `${total} total photos found  |  Previewing ${data.preview.length}`;
    } catch (e) {
        statusEl.textContent = 'Error: ' + e.message;
    } finally {
        btn.disabled = false;
    }
}

// ====================================================================
// Download
// ====================================================================

function getActiveTab() {
    const active = document.querySelector('.tab-btn.active');
    return active ? active.dataset.tab : 'interestingness';
}

function gatherParams() {
    const tab = getActiveTab();
    const params = {
        size_key: document.getElementById('photo-size').value,
        embed_metadata: document.getElementById('embed-metadata').checked,
        filename_template: document.getElementById('filename-tmpl').value || '{title}_{id}',
    };

    if (tab === 'interestingness') {
        params.tab_type = 'interestingness';
        params.date = document.getElementById('int-date').value.trim();
        params.count = parseInt(document.getElementById('int-count').value) || 500;
        if (userNsid) params.user_id = userNsid;
    } else if (tab === 'search') {
        params.tab_type = 'search';
        params.text = document.getElementById('search-text').value.trim();
        params.tags = document.getElementById('search-tags').value.trim();
        params.tag_mode = document.querySelector('input[name="tag-mode"]:checked').value;
        params.sort = document.getElementById('sort').value;
        params.license_ids = document.getElementById('license').value;
        params.count = parseInt(document.getElementById('search-count').value) || 100;
        if (userNsid) params.user_id = userNsid;
    } else if (tab === 'user-album') {
        const mode = document.querySelector('input[name="user-mode"]:checked').value;
        if (!userNsid) {
            alert('Look up a user first.');
            return null;
        }
        params.user_nsid = userNsid;
        if (mode === 'photostream') {
            params.tab_type = 'user_photostream';
            params.count = parseInt(document.getElementById('user-count').value) || 500;
        } else {
            params.tab_type = 'album';
            const idx = parseInt(document.getElementById('album-select').value);
            if (isNaN(idx) || idx < 0 || idx >= userAlbums.length) {
                alert('Select an album first.');
                return null;
            }
            params.album_id = userAlbums[idx].id;
            params.album_title = userAlbums[idx].title;
        }
    }
    return params;
}

function setRunning(running) {
    document.getElementById('download-btn').disabled = running;
    document.getElementById('cancel-btn').disabled = !running;
}

function appendLog(msg) {
    const el = document.getElementById('log-output');
    el.textContent += msg + '\n';
    el.scrollTop = el.scrollHeight;
}

async function startDownload() {
    const params = gatherParams();
    if (!params) return;

    document.getElementById('log-output').textContent = '';
    document.getElementById('progress-bar').style.width = '0%';
    document.getElementById('progress-status').textContent = 'Starting...';
    document.getElementById('download-link-wrap').innerHTML = '';
    setRunning(true);

    try {
        const resp = await fetch('/api/download/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(params),
        });
        const data = await resp.json();
        if (data.error) {
            appendLog('Error: ' + data.error);
            setRunning(false);
            return;
        }
        currentJobId = data.job_id;

        // Open SSE
        eventSource = new EventSource('/api/download/progress/' + currentJobId);
        eventSource.onmessage = function(event) {
            const ev = JSON.parse(event.data);
            switch (ev.type) {
                case 'progress':
                    const pct = Math.round((ev.current / ev.total) * 100);
                    document.getElementById('progress-bar').style.width = pct + '%';
                    document.getElementById('progress-status').textContent =
                        `${ev.current}/${ev.total} photos`;
                    break;
                case 'log':
                    appendLog(ev.message);
                    break;
                case 'zipping':
                    document.getElementById('progress-status').textContent =
                        'Creating zip file...';
                    break;
                case 'complete':
                    appendLog(ev.message || 'Done.');
                    document.getElementById('progress-status').textContent = 'Done';
                    if (ev.file_ready) {
                        document.getElementById('download-link-wrap').innerHTML =
                            `<a class="download-link" href="/api/download/file/${ev.job_id}">Download Zip</a>`;
                    }
                    setRunning(false);
                    eventSource.close();
                    eventSource = null;
                    break;
                case 'error':
                    appendLog('Error: ' + ev.message);
                    document.getElementById('progress-status').textContent = 'Failed';
                    setRunning(false);
                    eventSource.close();
                    eventSource = null;
                    break;
                case 'cancelled':
                    appendLog('Operation cancelled.');
                    document.getElementById('progress-status').textContent = 'Cancelled';
                    setRunning(false);
                    eventSource.close();
                    eventSource = null;
                    break;
            }
        };
        eventSource.onerror = function() {
            appendLog('Connection lost.');
            setRunning(false);
            eventSource.close();
            eventSource = null;
        };
    } catch (e) {
        appendLog('Error: ' + e.message);
        setRunning(false);
    }
}

async function cancelDownload() {
    if (!currentJobId) return;
    document.getElementById('progress-status').textContent = 'Cancelling...';
    try {
        await fetch('/api/download/cancel/' + currentJobId, {method: 'POST'});
    } catch (e) {
        appendLog('Cancel error: ' + e.message);
    }
}
