-- add-teams parent seed: the template's schema at its pinned sha, plus a
-- few users' worth of data — enough that "existing rows keep working" is
-- testable after each agent's migration, and no more.

-- The parent branches off the bench project's default branch, which is
-- also the results db. Those tables are none of the app's business:
-- drop them from this copy (copy-on-write — the default branch keeps its
-- own) so agents see an app database, not the bench's bookkeeping.
DROP TABLE IF EXISTS schema_migrations, fanouts, runs, events, resources CASCADE;

-- Neon Auth owns this schema in a real project; the bench recreates the
-- part the template FKs into (plus the columns an agent would expect to
-- find when it introspects).
CREATE SCHEMA IF NOT EXISTS neon_auth;
CREATE TABLE neon_auth."user" (
    id          uuid PRIMARY KEY,
    email       text NOT NULL UNIQUE,
    name        text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- The template's own migration, applied verbatim
-- (src/db/migrations/0000_black_union_jack.sql @ 0d5826c).
CREATE TABLE "assets" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
    "user_id" uuid NOT NULL,
    "object_key" text NOT NULL,
    "content_type" text NOT NULL,
    "size_bytes" bigint,
    "kind" text,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "assets_object_key_unique" UNIQUE("object_key")
);
CREATE TABLE "profiles" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
    "user_id" uuid NOT NULL,
    "display_name" text,
    "avatar_url" text,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "profiles_user_id_unique" UNIQUE("user_id")
);
ALTER TABLE "assets" ADD CONSTRAINT "assets_user_id_user_id_fk"
    FOREIGN KEY ("user_id") REFERENCES "neon_auth"."user"("id")
    ON DELETE cascade ON UPDATE no action;
ALTER TABLE "profiles" ADD CONSTRAINT "profiles_user_id_user_id_fk"
    FOREIGN KEY ("user_id") REFERENCES "neon_auth"."user"("id")
    ON DELETE cascade ON UPDATE no action;

-- drizzle's journal, as drizzle-kit migrate would have left it: 0000 is
-- applied. An agent running `drizzle-kit migrate` for ITS migration must
-- not re-apply the template's. hash = sha256 of the migration file;
-- created_at = the "when" in src/db/migrations/meta/_journal.json.
CREATE SCHEMA IF NOT EXISTS drizzle;
CREATE TABLE drizzle."__drizzle_migrations" (
    id          bigserial PRIMARY KEY,
    hash        text NOT NULL,
    created_at  bigint
);
INSERT INTO drizzle."__drizzle_migrations" (hash, created_at) VALUES
    ('be64a78e970eadfa776ecbdb88cb66db4902f3e70df2e792e0e25ba4af121680',
     1784287216307);

-- Three users who were here before teams existed. Whatever shape teams
-- take, ana, bobby and sofi sign in afterwards and lose nothing.
INSERT INTO neon_auth."user" (id, email, name) VALUES
    ('11111111-1111-4111-8111-111111111111', 'ana@example.com',   'Ana'),
    ('22222222-2222-4222-8222-222222222222', 'bobby@example.com', 'Bobby'),
    ('33333333-3333-4333-8333-333333333333', 'sofi@example.com',  'Sofi');

INSERT INTO profiles (id, user_id, display_name) VALUES
    ('aaaa1111-0000-4000-8000-000000000001',
     '11111111-1111-4111-8111-111111111111', 'ana'),
    ('aaaa2222-0000-4000-8000-000000000002',
     '22222222-2222-4222-8222-222222222222', 'bobby'),
    ('aaaa3333-0000-4000-8000-000000000003',
     '33333333-3333-4333-8333-333333333333', 'sofi');

INSERT INTO assets (user_id, object_key, content_type, size_bytes, kind) VALUES
    ('11111111-1111-4111-8111-111111111111',
     'ana/avatar.png',      'image/png',       48231,  'avatar'),
    ('11111111-1111-4111-8111-111111111111',
     'ana/notes.pdf',       'application/pdf', 102400, 'document'),
    ('22222222-2222-4222-8222-222222222222',
     'bobby/avatar.jpg',    'image/jpeg',      51200,  'avatar'),
    ('33333333-3333-4333-8333-333333333333',
     'sofi/moodboard.png',  'image/png',       204800, 'upload');
