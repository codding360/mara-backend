from supabase import create_client, Client

from app.core.config import get_config

config = get_config()

supabase: Client = create_client(
    config.SUPABASE_URL,
    config.SUPABASE_KEY
)
