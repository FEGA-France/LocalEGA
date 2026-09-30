PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS files (
    accession_id     text PRIMARY KEY,

    url              text,
    filepath         text,

    display_name     text NOT NULL,
    version          text, -- can be null
    filesize         bigint, 

    -- auditing
    created_at     bigint NOT NULL DEFAULT (unixepoch('now'))
);

-- no need for AUTOINCREMENT
-- See: https://sqlite.org/autoinc.html#summary
CREATE TABLE IF NOT EXISTS jobs (

    -- id               integer PRIMARY KEY,
    -- url              text NOT NULL,

    url              text PRIMARY KEY,

    correlation_id   text, -- info

    sha256           text, -- hex
    filepath         text,

    filesize         bigint, 

    accession_id     text,

    filename         text   GENERATED ALWAYS AS (replace(file, rtrim(file, replace(url, '.', '')), '')) VIRTUAL,

    status           text NOT NULL,
    error            text, -- in case of errors. NULL = no error

    -- auditing
    created_at     bigint NOT NULL DEFAULT (unixepoch('now')),
    edited_at      bigint NOT NULL DEFAULT (unixepoch('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id               integer PRIMARY KEY,

    correlation_id text NOT NULL,
    routing_key    text NOT NULL,
    message        text NOT NULL, -- already json formatted

    -- auditing
    created_at     bigint NOT NULL DEFAULT (unixepoch('now'))
);


-- We store sha256 hashes to avoid repetitions.
CREATE TABLE IF NOT EXISTS accession (

    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256     text UNIQUE,

    -- auditing
    created_at     bigint NOT NULL DEFAULT (unixepoch('now'))
);


CREATE TRIGGER IF NOT EXISTS on_job_update AFTER UPDATE ON jobs
BEGIN UPDATE jobs SET edited_at = unixepoch('now') WHERE url = NEW.url; END;
