-- Planted: lock-heavy / unsafe migration for Squawk (catalog C4)
BEGIN;
ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT '';
CREATE INDEX CONCURRENTLY idx_users_email ON users (email);
COMMIT;
