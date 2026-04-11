import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "laneyes-dev-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(DATA_DIR, 'laneyes.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Network settings
    NETWORK_CIDR = os.environ.get("NETWORK_CIDR", "192.168.1.0/24")
    SCAN_TIMEOUT = int(os.environ.get("SCAN_TIMEOUT", "30"))
