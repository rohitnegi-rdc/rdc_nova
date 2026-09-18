"""Read-only, narrowly scoped support-thread export. Disabled without a secret."""

import asyncio
import base64
import datetime as dt
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
import zipfile
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.background import BackgroundTask
from starlette.responses import Response

router = APIRouter()
DEFAULT_ADMIN_IDS = ['a49a4c0b-b8e0-41d1-88be-8d5798044ed9']
INDIA = ZoneInfo('Asia/Kolkata')
MAX_MESSAGES = 10000
MAX_BYTES = 64 * 1024 * 1024


def get_admin_ids():
    """Trusted server configuration, never caller-controlled selection."""
    configured = os.environ.get('KNOWLEDGE_EXPORT_ADMIN_IDS')
    if configured is None:
        return DEFAULT_ADMIN_IDS.copy()
    values = configured.split(',')
    try:
        if not 1 <= len(values) <= 50:
            raise ValueError()
        return list(dict.fromkeys(str(uuid.UUID(value.strip())) for value in values))
    except ValueError:
        raise HTTPException(503, 'Invalid KNOWLEDGE_EXPORT_ADMIN_IDS: configure 1–50 comma-separated UUIDs') from None


def date_bounds(start, end, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    low = dt.datetime.combine(start, dt.time.min, INDIA) if start else dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    high = dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, INDIA) if end and end < now.astimezone(INDIA).date() else now
    if low >= high:
        raise HTTPException(422, 'from must not be later than to/current time')
    return int(low.timestamp() * 10**9), int(high.timestamp() * 10**9)


class ExportGuard:
    """Atomic, persistent limits for workers sharing one local data volume.

    An OS file lock recovers from worker crashes. No proxy headers are trusted.
    Deploy one app replica; a shared network filesystem is not supported.
    """

    def __init__(self, path):
        self.path = Path(path)
        self._lock = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS global_state (id INTEGER PRIMARY KEY, day TEXT, attempts INTEGER, lease TEXT, lease_until REAL)')
            db.execute("INSERT OR IGNORE INTO global_state VALUES (1, '', 0, '', 0)")
            db.execute('CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, window REAL, attempts INTEGER, banned_until REAL)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=1)

    def admit(self, client, authenticated, now=None):
        now = time.time() if now is None else now
        key = hashlib.sha256(client.encode()).hexdigest()
        rejection = None
        token = None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM clients WHERE window < ? AND banned_until < ?', (now - 86400, now))
            row = db.execute('SELECT window, attempts, banned_until FROM clients WHERE id=?', (key,)).fetchone()
            window, count, banned = row or (now, 0, 0)
            if banned > now:
                rejection = (429, 'Temporarily blocked for excessive requests', int(banned - now) + 1)
            else:
                if now - window >= 60:
                    window, count = now, 0
                count += 1
                if count >= 10:
                    banned = now + 3600
                    rejection = (429, 'Temporarily blocked for excessive requests', 3600)
                db.execute('INSERT OR REPLACE INTO clients VALUES (?, ?, ?, ?)', (key, window, count, banned))
            if rejection is None and authenticated:
                day = dt.datetime.fromtimestamp(now, INDIA).date().isoformat()
                old_day, attempts, lease, until = db.execute('SELECT day, attempts, lease, lease_until FROM global_state WHERE id=1').fetchone()
                attempts = attempts if old_day == day else 0
                if attempts >= 5:
                    tomorrow = dt.datetime.combine(dt.datetime.fromtimestamp(now, INDIA).date() + dt.timedelta(days=1), dt.time.min, INDIA)
                    rejection = (429, 'Daily export limit reached (5 attempts)', int(tomorrow.timestamp() - now) + 1)
                else:
                    attempts += 1
                    import fcntl
                    lock = self.path.with_suffix('.lock').open('a+b')
                    try:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        lock.close()
                        rejection = (409, 'Another export is already running', max(1, int(until - now) + 1))
                    else:
                        self._lock = lock
                        token, until = str(uuid.uuid4()), now + 600
                        lease = token
                db.execute('UPDATE global_state SET day=?, attempts=?, lease=?, lease_until=? WHERE id=1', (day, attempts, lease, until))
        if rejection:
            code, detail, retry = rejection
            raise HTTPException(code, detail, headers={'Retry-After': str(retry)})
        return token

    def release(self, token):
        try:
            with self.connect() as db:
                db.execute("UPDATE global_state SET lease='', lease_until=0 WHERE id=1 AND lease=?", (token,))
        finally:
            if self._lock is not None:
                self._lock.close()
                self._lock = None


async def load_threads(start, end):
    """Select by admin reply date; retain full selected threads, not one reply."""
    from sqlalchemy import or_, select
    from open_webui.internal.db import get_async_db_context
    from open_webui.models.messages import Message
    from open_webui.models.channels import Channel, ChannelFile
    from open_webui.models.files import File

    admin_ids = get_admin_ids()
    admin_id_set = set(admin_ids)

    async with get_async_db_context() as db:
        replies = (await db.execute(select(Message).where(Message.user_id.in_(admin_ids), Message.created_at >= start, Message.created_at < end).limit(MAX_MESSAGES + 1))).scalars().all()
        if len(replies) > MAX_MESSAGES:
            raise HTTPException(413, 'Too many replies; use a smaller date range')
        roots = {m.parent_id or m.reply_to_id for m in replies if m.parent_id or m.reply_to_id}
        # Replies without a parent/link cannot safely be paired by proximity.
        unpaired = [{'id': m.id, 'content': m.content, 'reason': 'No thread or reply link'} for m in replies if not m.parent_id and not m.reply_to_id]
        if not replies:
            return [], unpaired
        unlinked_ids = {m.id for m in replies if not m.parent_id and not m.reply_to_id}
        messages = (await db.execute(select(Message).where(or_(Message.id.in_(roots | unlinked_ids), Message.parent_id.in_(roots), Message.reply_to_id.in_(roots))).order_by(Message.created_at, Message.id).limit(MAX_MESSAGES + 1))).scalars().all()
        if len(messages) > MAX_MESSAGES:
            raise HTTPException(413, 'Too many thread messages; use a smaller date range')
        ids = [m.id for m in messages]
        links = (await db.execute(select(ChannelFile.message_id, File).outerjoin(File, File.id == ChannelFile.file_id).where(ChannelFile.message_id.in_(ids)))).all()
        attachments = {}
        for message_id, file in links:
            attachments.setdefault(message_id, []).append(file)
        # Legacy messages can reference uploads without a channel_file row.
        referenced_ids = {f.get('id') for m in messages for f in (m.data or {}).get('files', []) if isinstance(f, dict) and f.get('id')}
        referenced = {f.id: f for f in (await db.execute(select(File).where(File.id.in_(referenced_ids)))).scalars().all()}
        for m in messages:
            existing = {f.id for f in attachments.get(m.id, []) if f}
            for media in (m.data or {}).get('files', []):
                if isinstance(media, dict) and media.get('id') and media['id'] not in existing:
                    attachments.setdefault(m.id, []).append(referenced.get(media['id']))
                    existing.add(media['id'])
        channels = dict((await db.execute(select(Channel.id, Channel.name).where(Channel.id.in_({m.channel_id for m in messages})))).all())
        by_id = {m.id: m for m in messages}
        output = []
        def serialize(m):
            media = [{'file_id': f.id, 'filename': f.filename, 'meta': f.meta, '_path': f.path} if f else {'status': 'missing_record'} for f in attachments.get(m.id, [])]
            # Never fetch arbitrary URLs (SSRF); explicitly report inline/URL-only media.
            media.extend({'status': 'needs_media_review', '_inline': f.get('url')} for f in (m.data or {}).get('files', []) if isinstance(f, dict) and not f.get('id'))
            return {'id': m.id, 'user_id': m.user_id, 'is_admin_reply': m.user_id in admin_id_set, 'content': m.content, 'created_at_ns': m.created_at, 'parent_id': m.parent_id, 'reply_to_id': m.reply_to_id, 'data': m.data, 'meta': m.meta, 'attachments': media}
        for entry in unpaired:
            if entry['id'] in by_id:
                entry['message'] = serialize(by_id[entry['id']])
        for root in sorted(roots):
            question = by_id.get(root)
            if not question:
                unpaired.append({'id': root, 'reason': 'Original question missing'})
                unpaired.extend({'id': m.id, 'reason': 'Original question missing', 'message': serialize(m)} for m in messages if m.parent_id == root or m.reply_to_id == root)
                continue
            thread = [m for m in messages if m.parent_id == root or m.reply_to_id == root]
            output.append({'question': serialize(question), 'channel_name': channels.get(question.channel_id), 'replies': [serialize(m) for m in thread]})
        return output, unpaired


async def build_archive(start, end):
    admin_ids = get_admin_ids()
    threads, unpaired = await load_threads(start, end)
    missing = []
    buffer = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:
        seen = {}
        groups = [[thread['question'], *thread['replies']] for thread in threads]
        groups.append([entry['message'] for entry in unpaired if 'message' in entry])
        for group in groups:
            for message in group:
                for media in message['attachments']:
                    path = media.pop('_path', None)
                    inline = media.pop('_inline', None)
                    file_id = media.get('file_id')
                    if file_id and file_id in seen:
                        media.update(seen[file_id])
                        continue
                    try:
                        if isinstance(inline, str) and inline.startswith('data:image/'):
                            header, encoded = inline.split(',', 1)
                            extensions = {'data:image/png;base64': '.png', 'data:image/jpeg;base64': '.jpg', 'data:image/gif;base64': '.gif', 'data:image/webp;base64': '.webp'}
                            if header not in extensions:
                                raise ValueError('Unsupported inline image')
                            if len(encoded) > MAX_BYTES * 4 // 3 + 4:
                                raise HTTPException(413, 'Inline image too large')
                            content = base64.b64decode(encoded, validate=True)
                            name = 'attachments/' + str(uuid.uuid4()) + extensions[header]
                            media['source_type'] = 'inline_image'
                        else:
                            if not path:
                                raise FileNotFoundError()
                            from open_webui.storage.provider import Storage
                            resolved = await asyncio.to_thread(Storage.get_file, path)
                            def read_media():
                                with Path(resolved).open('rb') as stream:
                                    return stream.read(MAX_BYTES + 1)
                            content = await asyncio.to_thread(read_media)
                            name = 'attachments/' + str(uuid.UUID(file_id)) + Path(media['filename']).suffix[:15]
                        total += len(content)
                        if total > MAX_BYTES:
                            raise HTTPException(413, 'Attachments exceed 64 MiB; use a smaller date range')
                        archive.writestr(name, content)
                        media.update({'archive_path': name, 'status': 'included'})
                    except HTTPException:
                        raise
                    except Exception:
                        media['status'] = 'unavailable'
                        missing.append({'message_id': message['id'], 'file_id': file_id})
                    if file_id:
                        seen[file_id] = {k: media[k] for k in ('archive_path', 'status') if k in media}
        payload = {'schema_version': 2, 'admin_ids': admin_ids, 'timezone': 'Asia/Kolkata', 'from_ns': start, 'to_exclusive_ns': end, 'selection': 'admin reply date; complete selected threads', 'threads': threads, 'unpaired': unpaired, 'missing_attachments': missing, 'complete': not missing and not unpaired}
        raw = json.dumps(payload, ensure_ascii=False).encode()
        if total + len(raw) > MAX_BYTES:
            raise HTTPException(413, 'Export exceeds 64 MiB; use a smaller date range')
        archive.writestr('threads.json', raw)
    return buffer.getvalue()


@router.get('/export')
async def export(request: Request, from_date: dt.date | None = Query(None, alias='from'), to_date: dt.date | None = Query(None, alias='to')):
    secret = os.environ.get('KNOWLEDGE_EXPORT_SECRET', '')
    if len(secret) < 32:
        raise HTTPException(503, 'Knowledge export is disabled')
    if request.url.scheme != 'https' and os.environ.get('KNOWLEDGE_EXPORT_ALLOW_HTTP', '').lower() != 'true':
        raise HTTPException(400, 'HTTPS is required')
    provided = request.headers.get('authorization', '')
    authenticated = hmac.compare_digest(provided.encode(), ('Bearer ' + secret).encode())
    try:
        from open_webui.env import DATA_DIR
        guard = ExportGuard(os.environ.get('KNOWLEDGE_EXPORT_STATE_PATH', str(Path(DATA_DIR) / 'knowledge-export-limits.sqlite')))
        token = await asyncio.to_thread(guard.admit, request.client.host if request.client else 'unknown', authenticated)
    except (sqlite3.Error, OSError):
        raise HTTPException(503, 'Export protection is unavailable') from None
    if not authenticated:
        raise HTTPException(401, 'Invalid export credentials')
    try:
        start, end = date_bounds(from_date, to_date)
        data = await asyncio.wait_for(build_archive(start, end), timeout=120)
    except asyncio.TimeoutError:
        await asyncio.to_thread(guard.release, token)
        raise HTTPException(504, 'Export timed out; use a smaller date range') from None
    except BaseException:
        await asyncio.to_thread(guard.release, token)
        raise
    return Response(data, media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="kanhaiya-thread-export.zip"', 'Cache-Control': 'no-store'}, background=BackgroundTask(guard.release, token))
