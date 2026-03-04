import sqlite3
import os
from datetime import datetime

DB_NAME = "raj_photography.db"

def get_connection():
    """Returns a connection to the SQLite database."""
    return sqlite3.connect(DB_NAME)

def init_db():
    """Initializes the database with the required tables using raw SQL."""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Events Table (Updated with deletion tracking)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            event_name TEXT NOT NULL,
            watermark_path TEXT,
            qr_code_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_deleted INTEGER DEFAULT 0,
            deleted_at TIMESTAMP,
            status TEXT DEFAULT 'Active'
        )
    ''')
    
    # Check if columns exist
    cursor.execute("PRAGMA table_info(events)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'is_deleted' not in columns:
        cursor.execute('ALTER TABLE events ADD COLUMN is_deleted INTEGER DEFAULT 0')
    if 'deleted_at' not in columns:
        cursor.execute('ALTER TABLE events ADD COLUMN deleted_at TIMESTAMP')
    if 'status' not in columns:
        cursor.execute("ALTER TABLE events ADD COLUMN status TEXT DEFAULT 'Active'")

    # 2. Watermarks Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watermarks (
            watermark_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 3. Media Table (Updated with deletion tracking)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS media (
            media_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            file_type TEXT NOT NULL,
            original_file_path TEXT NOT NULL,
            watermarked_file_path TEXT NOT NULL,
            thumbnail_path TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_deleted INTEGER DEFAULT 0,
            deleted_at TIMESTAMP,
            file_hash TEXT,
            FOREIGN KEY (event_id) REFERENCES events (event_id) ON DELETE CASCADE
        )
    ''')
    
    # Check if columns exist (for migration)
    cursor.execute("PRAGMA table_info(media)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'thumbnail_path' not in columns:
        cursor.execute('ALTER TABLE media ADD COLUMN thumbnail_path TEXT')
    if 'is_deleted' not in columns:
        cursor.execute('ALTER TABLE media ADD COLUMN is_deleted INTEGER DEFAULT 0')
    if 'deleted_at' not in columns:
        cursor.execute('ALTER TABLE media ADD COLUMN deleted_at TIMESTAMP')
    if 'file_hash' not in columns:
        cursor.execute('ALTER TABLE media ADD COLUMN file_hash TEXT')

    # 4. Leads Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact TEXT NOT NULL,
            event_type TEXT,
            captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Check if columns exist for migration (Phase 16)
    cursor.execute("PRAGMA table_info(leads)")
    l_columns = [col[1] for col in cursor.fetchall()]
    # SQLite doesn't support easy column renaming in some versions, 
    # but we can try migrating them one by one if they don't exist
    if 'contact_info' in l_columns and 'contact' not in l_columns:
        cursor.execute('ALTER TABLE leads RENAME COLUMN contact_info TO contact')
    if 'created_at' in l_columns and 'captured_at' not in l_columns:
        cursor.execute('ALTER TABLE leads RENAME COLUMN created_at TO captured_at')
    if 'lead_id' in l_columns and 'id' not in l_columns:
        cursor.execute('ALTER TABLE leads RENAME COLUMN lead_id TO id')
    
    # 5. Admin Auth Table (Phase 16)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_auth (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            password_hash TEXT NOT NULL,
            recovery_key_hash TEXT NOT NULL
        )
    ''')

    conn.commit()
    conn.close()
    print("Database initialized successfully.")

# CRUD for Events
def create_event(event_id, event_name, watermark_path, qr_code_path):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO events (event_id, event_name, watermark_path, qr_code_path)
        VALUES (?, ?, ?, ?)
    ''', (event_id, event_name, watermark_path, qr_code_path))
    conn.commit()
    conn.close()

def get_event(event_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM events WHERE event_id = ?', (event_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_all_events():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM events WHERE is_deleted = 0 ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_deleted_events():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM events WHERE is_deleted = 1 ORDER BY deleted_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return rows

def set_event_status(event_id, status):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE events SET status = ? WHERE event_id = ?', (status, event_id))
    conn.commit()
    conn.close()

def soft_delete_event(event_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE events 
        SET is_deleted = 1, deleted_at = CURRENT_TIMESTAMP 
        WHERE event_id = ?
    ''', (event_id,))
    conn.commit()
    conn.close()

def restore_event(event_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE events 
        SET is_deleted = 0, deleted_at = NULL 
        WHERE event_id = ?
    ''', (event_id,))
    conn.commit()
    conn.close()

def cleanup_expired_events():
    """Permanently deletes events that have been in the recycle bin for more than 30 days."""
    conn = get_connection()
    cursor = conn.cursor()
    # SQLite doesn't have a built-in '30 days' interval syntax as clean as Postgres, 
    # but we can use date() functions.
    cursor.execute("SELECT event_id, watermark_path, qr_code_path FROM events WHERE is_deleted = 1 AND deleted_at < datetime('now', '-30 days')")
    expired = cursor.fetchall()
    
    # We return the list so the app can clean up files too
    conn.close()
    return expired

def delete_event(event_id):
    conn = get_connection()
    cursor = conn.cursor()
    # Cascading delete is handled by Foreign Key in schema (ON DELETE CASCADE)
    cursor.execute('DELETE FROM events WHERE event_id = ?', (event_id,))
    conn.commit()
    conn.close()

# CRUD for Media
def get_all_media_for_migration():
    """Fetches all media that are missing thumbnails."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT media_id, event_id, file_type, original_file_path, watermarked_file_path, thumbnail_path FROM media WHERE thumbnail_path IS NULL')
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_media_thumbnail(media_id, thumbnail_path):
    """Updates the thumbnail path for a specific media item."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE media SET thumbnail_path = ? WHERE media_id = ?', (thumbnail_path, media_id))
    conn.commit()
    conn.close()

def add_media(event_id, file_type, original_path, watermarked_path, thumbnail_path=None, file_hash=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO media (event_id, file_type, original_file_path, watermarked_file_path, thumbnail_path, file_hash)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (event_id, file_type, original_path, watermarked_path, thumbnail_path, file_hash))
    conn.commit()
    conn.close()

def check_duplicate_media(event_id, file_hash):
    """Checks if a file with the same hash exists in the event (Active only)."""
    if not file_hash: return False
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT media_id FROM media WHERE event_id = ? AND file_hash = ? AND is_deleted = 0', (event_id, file_hash))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def get_event_media(event_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM media WHERE event_id = ? AND is_deleted = 0 ORDER BY uploaded_at DESC, media_id DESC', (event_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def soft_delete_media(media_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE media 
        SET is_deleted = 1, deleted_at = CURRENT_TIMESTAMP 
        WHERE media_id = ?
    ''', (media_id,))
    conn.commit()
    conn.close()

def restore_media(media_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE media 
        SET is_deleted = 0, deleted_at = NULL 
        WHERE media_id = ?
    ''', (media_id,))
    conn.commit()
    conn.close()

def get_deleted_media():
    conn = get_connection()
    cursor = conn.cursor()
    # Updated to ensure thumbnail_path is included in the selection
    cursor.execute('SELECT * FROM media WHERE is_deleted = 1 ORDER BY deleted_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return rows

def cleanup_expired_media():
    """Permanently deletes media that has been in the recycle bin for more than 30 days."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT media_id, original_file_path, watermarked_file_path, thumbnail_path FROM media WHERE is_deleted = 1 AND deleted_at < datetime('now', '-30 days')")
    expired = cursor.fetchall()
    conn.close()
    return expired

def delete_media(media_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM media WHERE media_id = ?', (media_id,))
    conn.commit()
    conn.close()

# CRUD for Leads
def add_lead(name, contact_info, event_type):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leads (name, contact, event_type)
        VALUES (?, ?, ?)
    ''', (name, contact_info, event_type))
    conn.commit()
    conn.close()

def get_all_leads():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM leads ORDER BY captured_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return rows

# --- Admin Auth Functions ---

def get_admin_auth():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT password_hash, recovery_key_hash FROM admin_auth WHERE id = 1')
    res = cursor.fetchone()
    conn.close()
    return res

def save_admin_auth(pwd_hash, rec_hash):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO admin_auth (id, password_hash, recovery_key_hash) VALUES (1, ?, ?)', (pwd_hash, rec_hash))
    conn.commit()
    conn.close()

def update_admin_password(pwd_hash):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE admin_auth SET password_hash = ? WHERE id = 1', (pwd_hash,))
    conn.commit()
    conn.close()

# CRUD for Watermarks
def add_watermark(name, path):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO watermarks (name, path) VALUES (?, ?)', (name, path))
    conn.commit()
    conn.close()

def get_all_watermarks():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM watermarks ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return rows

def delete_watermark(watermark_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM watermarks WHERE watermark_id = ?', (watermark_id,))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
