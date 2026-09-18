"""Real SQL integration tests on disposable SQLite, never on application data."""
import asyncio
from contextlib import asynccontextmanager
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import BigInteger, Column, JSON, String, Text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from open_webui.routers import knowledge_export as api


@pytest.mark.parametrize('reply_link', ['parent_id', 'reply_to_id'])
@pytest.mark.parametrize('multiple_admins', [False, True])
def test_date_selection_full_threads_and_legacy_media(tmp_path, monkeypatch, reply_link, multiple_admins):
    first_admin = 'a49a4c0b-b8e0-41d1-88be-8d5798044ed9'
    second_admin = '11111111-1111-4111-8111-111111111111'
    monkeypatch.setenv('KNOWLEDGE_EXPORT_ADMIN_IDS', ','.join([first_admin, second_admin] if multiple_admins else [first_admin]))
    base = declarative_base()
    class Message(base):
        __tablename__ = 'message'
        id = Column(String, primary_key=True)
        user_id = Column(String)
        channel_id = Column(String)
        parent_id = Column(String)
        reply_to_id = Column(String)
        created_at = Column(BigInteger)
        content = Column(Text)
        data = Column(JSON)
        meta = Column(JSON)
    class Channel(base):
        __tablename__ = 'channel'
        id = Column(String, primary_key=True)
        name = Column(String)
    class File(base):
        __tablename__ = 'file'
        id = Column(String, primary_key=True)
        filename = Column(String)
        path = Column(String)
        meta = Column(JSON)
    class ChannelFile(base):
        __tablename__ = 'channel_file'
        id = Column(String, primary_key=True)
        message_id = Column(String)
        file_id = Column(String)

    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'source.sqlite'))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as db:
            await db.run_sync(base.metadata.create_all)
        async with sessions() as db:
            db.add_all([
                Channel(id='channel', name='batching'),
                Message(id='q', user_id='operator', channel_id='channel', content='Throughput formula?', created_at=1, data={'files': [{'id': 'image'}]}),
                Message(id='a1', user_id=first_admin, channel_id='channel', content='Checking', created_at=100, **{reply_link: 'q'}),
                Message(id='clarification', user_id='operator', channel_id='channel', content='For one cum', created_at=110, **{reply_link: 'q'}),
                Message(id='a2', user_id=first_admin, channel_id='channel', content='Use screenshot formula', created_at=120, **{reply_link: 'q'}),
                Message(id='a3', user_id=first_admin, channel_id='channel', content='Final clarification after range', created_at=200, **{reply_link: 'q'}),
                Message(id='a4', user_id=second_admin, channel_id='channel', content='Second admin guidance', created_at=125, **{reply_link: 'q'}),
                Message(id='q3', user_id='operator', channel_id='channel', content='Second admin only thread', created_at=1),
                Message(id='c', user_id=second_admin, channel_id='channel', content='Solution by second admin', created_at=100, **{reply_link: 'q3'}),
                Message(id='q2', user_id='operator', content='Unrelated', created_at=2),
                Message(id='b', user_id='someone-else', parent_id='q2', created_at=100),
                Message(id='unlinked', user_id=first_admin, content='No parent', created_at=100),
                File(id='image', filename='formula.png', path='/fixture.png'),
                ChannelFile(id='cf', message_id='a2', file_id='image'),
            ])
            await db.commit()
        @asynccontextmanager
        async def context():
            async with sessions() as db:
                yield db
        monkeypatch.setitem(sys.modules, 'open_webui.internal.db', SimpleNamespace(get_async_db_context=context))
        monkeypatch.setitem(sys.modules, 'open_webui.models.messages', SimpleNamespace(Message=Message))
        monkeypatch.setitem(sys.modules, 'open_webui.models.channels', SimpleNamespace(Channel=Channel, ChannelFile=ChannelFile))
        monkeypatch.setitem(sys.modules, 'open_webui.models.files', SimpleNamespace(File=File))
        try:
            threads, unpaired = await api.load_threads(90, 130)
            assert len(threads) == (2 if multiple_admins else 1)
            assert threads[0]['question']['id'] == 'q'
            assert [m['id'] for m in threads[0]['replies']] == ['a1', 'clarification', 'a2', 'a4', 'a3']
            assert threads[0]['replies'][3]['is_admin_reply'] is multiple_admins
            assert not threads[0]['replies'][1]['is_admin_reply']
            if multiple_admins:
                assert threads[1]['question']['id'] == 'q3'
                assert threads[1]['replies'][0]['is_admin_reply']
            assert threads[0]['question']['attachments'][0]['file_id'] == 'image'
            assert threads[0]['replies'][2]['attachments'][0]['file_id'] == 'image'
            assert unpaired[0]['id'] == 'unlinked'
        finally:
            await engine.dispose()
    asyncio.run(run())
