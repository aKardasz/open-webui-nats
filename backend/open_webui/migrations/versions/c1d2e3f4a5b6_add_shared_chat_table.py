"""Add shared_chat table and migrate existing shares

Revision ID: c1d2e3f4a5b6
Revises: e1f2a3b4c5d6
Create Date: 2026-04-16 23:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b6'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None

chat_t = sa.table(
    'chat',
    sa.column('id', sa.Text),
    sa.column('user_id', sa.Text),
    sa.column('title', sa.Text),
    sa.column('chat', sa.JSON),
    sa.column('share_id', sa.Text),
    sa.column('created_at', sa.BigInteger),
    sa.column('updated_at', sa.BigInteger),
    sa.column('archived', sa.Boolean),
    sa.column('meta', sa.JSON),
)

shared_chat_t = sa.table(
    'shared_chat',
    sa.column('id', sa.Text),
    sa.column('chat_id', sa.Text),
    sa.column('user_id', sa.Text),
    sa.column('title', sa.Text),
    sa.column('chat', sa.JSON),
    sa.column('created_at', sa.BigInteger),
    sa.column('updated_at', sa.BigInteger),
)

chat_message_t = sa.table(
    'chat_message',
    sa.column('chat_id', sa.Text),
)


def upgrade():
    conn = op.get_bind()

    op.create_table(
        'shared_chat',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('chat_id', sa.Text(), sa.ForeignKey('chat.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('chat', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.BigInteger(), nullable=True),
        sa.Column('updated_at', sa.BigInteger(), nullable=True),
    )

    shared_rows = conn.execute(
        sa.select(
            chat_t.c.id,
            chat_t.c.user_id,
            chat_t.c.title,
            chat_t.c.chat,
            chat_t.c.created_at,
            chat_t.c.updated_at,
        ).where(chat_t.c.user_id.like('shared-%'))
    ).fetchall()

    for row in shared_rows:
        share_token = row.id
        original_chat_id = row.user_id.replace('shared-', '', 1)

        original = conn.execute(sa.select(chat_t.c.user_id).where(chat_t.c.id == original_chat_id)).fetchone()
        if not original:
            continue

        conn.execute(
            shared_chat_t.insert().values(
                id=share_token,
                chat_id=original_chat_id,
                user_id=original.user_id,
                title=row.title,
                chat=row.chat,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
        conn.execute(chat_t.update().where(chat_t.c.id == original_chat_id).values(share_id=share_token))

    conn.execute(
        chat_message_t.delete().where(
            chat_message_t.c.chat_id.in_(sa.select(chat_t.c.id).where(chat_t.c.user_id.like('shared-%')))
        )
    )
    conn.execute(chat_t.delete().where(chat_t.c.user_id.like('shared-%')))


def downgrade():
    conn = op.get_bind()
    shared_rows = conn.execute(
        sa.select(
            shared_chat_t.c.id,
            shared_chat_t.c.chat_id,
            shared_chat_t.c.title,
            shared_chat_t.c.chat,
            shared_chat_t.c.created_at,
            shared_chat_t.c.updated_at,
        )
    ).fetchall()

    for row in shared_rows:
        conn.execute(
            chat_t.insert().values(
                id=row.id,
                user_id=f'shared-{row.chat_id}',
                title=row.title,
                chat=row.chat,
                created_at=row.created_at,
                updated_at=row.updated_at,
                archived=False,
                meta={},
            )
        )

    op.drop_table('shared_chat')
