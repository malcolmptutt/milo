-- Run this once against your Postgres database (e.g. via the Neon SQL editor,
-- or `psql "$DATABASE_URL" -f schema.sql`).

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    google_sub TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    name TEXT,
    picture TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expiry TIMESTAMPTZ NOT NULL,
    scope TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'business',
    due_at TIMESTAMPTZ,
    completed BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
