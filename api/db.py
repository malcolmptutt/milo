"""
Thin data-access layer for the MiLO PoC.

Uses plain psycopg2 with raw SQL rather than an ORM to keep the
Vercel Function bundle small and the behavior easy to follow.
Each call opens and closes its own connection, which is the right
pattern for short-lived serverless functions.
"""

import os
import uuid

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it in your Vercel project's "
            "Environment Variables (see README for how to get one from Neon)."
        )
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def upsert_user(google_sub, email, name, picture):
    new_id = str(uuid.uuid4())
    with get_conn() as conn:
        with conn.cursor() as cur:
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
            return str(row["id"])


def get_user(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, name, picture FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def save_tokens(user_id, access_token, refresh_token, expiry, scope):
    with get_conn() as conn:
        with conn.cursor() as cur:
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


def get_tokens(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT access_token, refresh_token, expiry, scope
                FROM oauth_tokens WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def list_tasks(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, category, due_at, completed
                FROM tasks WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def create_task(user_id, title, category, due_at):
    task_id = str(uuid.uuid4())
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tasks (id, user_id, title, category, due_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, title, category, due_at, completed
                """,
                (task_id, user_id, title, category, due_at),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row)


def update_task(task_id, user_id, **fields):
    allowed = {"title", "category", "due_at", "completed"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return None
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [task_id, user_id]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE tasks SET {set_clause}
                WHERE id = %s AND user_id = %s
                RETURNING id, title, category, due_at, completed
                """,
                values,
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None


def delete_task(task_id, user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tasks WHERE id = %s AND user_id = %s",
                (task_id, user_id),
            )
            conn.commit()
