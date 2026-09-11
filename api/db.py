"""
Thin data-access layer for the MiLO PoC.

Uses pg8000 rather than psycopg2. psycopg2-binary ships a compiled C
extension that frequently fails to import on platforms that restrict
custom binaries (Vercel Functions included) -- it either isn't built
for the exact runtime, or the shared libpq library it depends on
isn't present. pg8000 implements the Postgres wire protocol in pure
Python, so there's nothing to fail to import. It costs a little raw
speed against psycopg2's C extension, which doesn't matter at PoC
traffic levels.

Each call opens and closes its own connection, which is the right
pattern for short-lived serverless functions.
"""

import os
import uuid
from urllib.parse import urlparse, unquote

import pg8000.dbapi

DATABASE_URL = os.environ.get("DATABASE_URL")


def _connection_params(url):
    parsed = urlparse(url)
    return {
        "user": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "database": parsed.path.lstrip("/"),
    }


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it in your Vercel project's "
            "Environment Variables (see README for how to get one from Neon)."
        )
    params = _connection_params(DATABASE_URL)
    return pg8000.dbapi.connect(
        user=params["user"],
        password=params["password"],
        host=params["host"],
        port=params["port"],
        database=params["database"],
        ssl_context=True,  # Neon (and most managed Postgres) requires SSL
    )


def _dictify(cur, row):
    if row is None:
        return None
    columns = [d[0] for d in cur.description]
    return dict(zip(columns, row))


def _dictify_all(cur):
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def upsert_user(google_sub, email, name, picture):
    new_id = str(uuid.uuid4())
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (id, google_sub, email, name, picture)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (google_sub) DO UPDATE
            SET email = EXCLUDED.email,
                name = EXCLUDED.name,
                picture = EXCLUDED.picture
            RETURNING id
            """,
            (new_id, google_sub, email, name, picture),
        )
        row = cur.fetchone()
        conn.commit()
        return str(row[0])
    finally:
        conn.close()


def get_user(user_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, email, name, picture FROM users WHERE id = %s",
            (user_id,),
        )
        return _dictify(cur, cur.fetchone())
    finally:
        conn.close()


def save_tokens(user_id, access_token, refresh_token, expiry, scope):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO oauth_tokens (user_id, access_token, refresh_token, expiry, scope)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
            SET access_token = EXCLUDED.access_token,
                refresh_token = COALESCE(EXCLUDED.refresh_token, oauth_tokens.refresh_token),
                expiry = EXCLUDED.expiry,
                scope = EXCLUDED.scope
            """,
            (user_id, access_token, refresh_token, expiry, scope),
        )
        conn.commit()
    finally:
        conn.close()


def get_tokens(user_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT access_token, refresh_token, expiry, scope
            FROM oauth_tokens WHERE user_id = %s
            """,
            (user_id,),
        )
        return _dictify(cur, cur.fetchone())
    finally:
        conn.close()


def list_tasks(user_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, category, due_at, completed
            FROM tasks WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        return _dictify_all(cur)
    finally:
        conn.close()


def create_task(user_id, title, category, due_at):
    task_id = str(uuid.uuid4())
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO tasks (id, user_id, title, category, due_at)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, title, category, due_at, completed
            """,
            (task_id, user_id, title, category, due_at),
        )
        result = _dictify(cur, cur.fetchone())
        conn.commit()
        return result
    finally:
        conn.close()


def update_task(task_id, user_id, **fields):
    allowed = {"title", "category", "due_at", "completed"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return None
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [task_id, user_id]
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE tasks SET {set_clause}
            WHERE id = %s AND user_id = %s
            RETURNING id, title, category, due_at, completed
            """,
            values,
        )
        result = _dictify(cur, cur.fetchone())
        conn.commit()
        return result
    finally:
        conn.close()


def delete_task(task_id, user_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM tasks WHERE id = %s AND user_id = %s",
            (task_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()
