"""
migrate_006_calendar_import.py - staging table + import link for the calendar import engine.
    python migrations/migrate_006_calendar_import.py --check
    python migrations/migrate_006_calendar_import.py
Idempotent. Only ADDS.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from migrate_001_planning import (connect, table_exists, column_info, index_exists,
                                  fk_exists, do, add_column, DRY)


def main():
    print("MODE:", "CHECK ONLY" if DRY else "APPLY")
    conn = connect()
    cur = conn.cursor()
    try:
        print("\n[1] calendar_import_batches")
        do(cur, "create calendar_import_batches",
           "CREATE TABLE IF NOT EXISTS calendar_import_batches ("
           " id INT NOT NULL AUTO_INCREMENT,"
           " academic_period_id INT NOT NULL,"
           " source_type ENUM('csv','xlsx','docx','pdf','image') NOT NULL,"
           " filename VARCHAR(255) NOT NULL,"
           " sha256 CHAR(64) NOT NULL,"
           " mode ENUM('append','replace') NOT NULL DEFAULT 'append',"
           " rows_json LONGTEXT NOT NULL,"
           " summary_json TEXT NULL,"
           " status ENUM('preview','committed','discarded') NOT NULL DEFAULT 'preview',"
           " created_by INT NULL,"
           " created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
           " committed_at DATETIME NULL,"
           " PRIMARY KEY (id),"
           " KEY idx_cib_period (academic_period_id),"
           " CONSTRAINT fk_cib_period FOREIGN KEY (academic_period_id) "
           "   REFERENCES academic_periods (id) ON DELETE CASCADE,"
           " CONSTRAINT fk_cib_user FOREIGN KEY (created_by) "
           "   REFERENCES users (id) ON DELETE SET NULL"
           ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci")

        print("\n[2] calendar_events.import_batch_id")
        add_column(cur, "calendar_events", "import_batch_id", "INT NULL")
        if not index_exists(cur, "calendar_events", "idx_ce_batch"):
            do(cur, "index idx_ce_batch",
               "ALTER TABLE calendar_events ADD INDEX idx_ce_batch (import_batch_id)")
        if table_exists(cur, "calendar_import_batches") and not fk_exists(cur, "calendar_events", "fk_ce_batch"):
            do(cur, "fk calendar_events.import_batch_id -> calendar_import_batches.id",
               "ALTER TABLE calendar_events ADD CONSTRAINT fk_ce_batch "
               "FOREIGN KEY (import_batch_id) REFERENCES calendar_import_batches (id) ON DELETE SET NULL")
        if not DRY:
            cur.execute("INSERT IGNORE INTO schema_migrations (name) VALUES ('006_calendar_import')")
    finally:
        cur.close()
        conn.close()
    print("\nFinished.")


if __name__ == "__main__":
    main()