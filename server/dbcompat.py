"""Small shim so the server also loads where the PostgreSQL driver cannot (for example a PC whose
security policy blocks psycopg's native library). With psycopg available, Jsonb is psycopg's own."""
try:
    from psycopg.types.json import Jsonb
except ImportError:                       # local test mode only; PostgreSQL always has psycopg
    class Jsonb:
        def __init__(self, obj, dumps=None):
            self.obj = obj
