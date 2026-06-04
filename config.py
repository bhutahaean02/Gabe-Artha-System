import os
from dotenv import load_dotenv

# Load environment variables dari file .env
load_dotenv()

# Menyimpan semua konfigurasi aplikasi dan database
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'koperasi_gabe_artha')
}

# Secret key untuk keamanan session (Login) dan flash messages
SECRET_KEY = os.getenv('SECRET_KEY', 'default_fallback_secret_key')