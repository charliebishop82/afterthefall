Versioned database migrations belong here once persistent data needs upgrading.

The initial creator sets `PRAGMA user_version = 1`. It must never be used to
upgrade an existing database. Future migrations must check the old version,
preserve historical records, execute transactionally, and advance the version
only on success. Back up the database before applying a migration.
