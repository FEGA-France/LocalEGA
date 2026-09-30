PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entries (
    inode             INTEGER PRIMARY KEY, -- no need for AUTOINCREMENT
    name              text NOT NULL,
    parent_inode      INT64 NOT NULL REFERENCES entries(inode) ON DELETE CASCADE
                                     NOT DEFERRABLE INITIALLY IMMEDIATE,
    ctime             INT64 NOT NULL DEFAULT (unixepoch('now')),
    mtime             INT64 NOT NULL DEFAULT (unixepoch('now')),
    nlink             INT NOT NULL DEFAULT 2,
    size              INT64 NOT NULL DEFAULT 0,
    is_dir            INT NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS names ON entries(parent_inode, name);

INSERT INTO entries(inode, name, parent_inode) VALUES (1, '/', 1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS files (
  inode         INTEGER PRIMARY KEY REFERENCES entries(inode) ON DELETE CASCADE
                                    NOT DEFERRABLE INITIALLY IMMEDIATE,
  mountpoint    text,
  rel_path      text,
  header        BLOB,
  payload_size  INT64 NOT NULL DEFAULT 0,
  prepend       BLOB,
  append        BLOB
);

CREATE TABLE IF NOT EXISTS extended_attributes (
    inode             INTEGER REFERENCES entries(inode) ON DELETE CASCADE
                              NOT DEFERRABLE INITIALLY IMMEDIATE,
    name              text NOT NULL,
    value             text NOT NULL,
    PRIMARY KEY(inode,name)
);

CREATE TRIGGER IF NOT EXISTS on_insert AFTER INSERT ON extended_attributes 
BEGIN UPDATE entries SET mtime = unixepoch('now'),
                         ctime = unixepoch('now')
      WHERE inode = NEW.inode;
END;

CREATE TRIGGER IF NOT EXISTS on_update AFTER UPDATE ON extended_attributes  
BEGIN UPDATE entries SET mtime = unixepoch('now'),
                         ctime = unixepoch('now')
      WHERE inode = NEW.inode;
END;

CREATE TRIGGER IF NOT EXISTS on_delete AFTER DELETE ON extended_attributes  
BEGIN UPDATE entries SET mtime = unixepoch('now'),
                         ctime = unixepoch('now')
      WHERE inode = NEW.inode;
END;
