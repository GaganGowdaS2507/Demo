import mysql.connector
from mysql.connector import pooling
from flask import g
from config import Config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- CONFIG ----------
DB_CONFIG = {
    "host": Config.DB_HOST,
    "port": Config.DB_PORT,
    "user": Config.DB_USER,
    "password": Config.DB_PASS,
    "database": Config.DB_NAME,
}

# ---------- CONNECTION POOL ----------
connection_pool = None

def init_db_pool():
    global connection_pool
    if connection_pool is None:
        connection_pool = pooling.MySQLConnectionPool(
            pool_name="attendance_pool",
            pool_size=5,
            **DB_CONFIG
        )

from flask import g

from flask import g

# def get_db():
#     global connection_pool

#     if connection_pool is None:
#         raise Exception("DB pool not initialized")

#     if 'db' not in g or g.db is None:
#         g.db = connection_pool.get_connection()

#     # 🔥 VERY IMPORTANT: ensure connection is alive
#     try:
#         g.db.ping(reconnect=True, attempts=3, delay=2)
#     except Exception:
#         g.db = connection_pool.get_connection()

#     return g.db

def get_db():
    global connection_pool

    if connection_pool is None:
        init_db_pool()

    db = g.get('db', None)
    if db is not None:
        try:
            if not db.is_connected():
                db = None
        except Exception:
            db = None

    if db is None:
        g.db = connection_pool.get_connection()
        g.db_pinged = False

    # Only ping once per request — not on every get_db()/get_cursor() call.
    if not g.get('db_pinged', False):
        try:
            g.db.ping(reconnect=True, attempts=2, delay=1)
            g.db_pinged = True
        except Exception:
            logger.warning("DB ping/reconnect failed, getting a fresh connection from the pool")
            g.db = connection_pool.get_connection()
            g.db_pinged = True

    return g.db

def close_db(e=None):
    g.pop('db_pinged', None)
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except Exception:
            logger.error("Error occurred while closing DB connection")
            pass

def get_cursor(dictionary=True):
    """Get a buffered cursor from the current request's DB connection."""
    conn = get_db()
    return conn.cursor(dictionary=dictionary, buffered=True)
# ---------- GENERIC QUERY FUNCTIONS ----------

def query_all(query, params=None):
    conn = get_db()
    cursor = get_cursor()
    cursor.execute(query, params or ())
    result = cursor.fetchall()
    cursor.close()
    return result

def query_one(query, params=None):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params or ())
    result = cursor.fetchone()
    cursor.close()
    return result

def execute(query, params=None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(query, params or ())
    conn.commit()
    cursor.close()

# ---------- SPECIFIC FUNCTIONS ----------

def get_students(dept=None):
    query = "SELECT * FROM students WHERE 1=1"
    params = []

    if dept:
        query += " AND department = %s"
        params.append(dept)

    return query_all(query, params)


def get_faculty(dept=None):
    query = "SELECT * FROM faculty WHERE 1=1"
    params = []

    if dept:
        query += " AND department = %s"
        params.append(dept)

    return query_all(query, params)


def get_subjects():
    query = "SELECT * FROM subjects"
    return query_all(query)


def add_student(name, roll_no, dept):
    query = """
    INSERT INTO students (name, roll_no, department)
    VALUES (%s, %s, %s)
    """
    execute(query, (name, roll_no, dept))


def get_attendance(student_id):
    query = """
    SELECT * FROM attendance
    WHERE student_id = %s
    """
    return query_all(query, (student_id,))