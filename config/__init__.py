import os

from .config import Config

config = Config()
os.environ["OPENAI_API_KEY"] = config.openai_api_key
logger = config.get_logger()

__all__ = ["config", "logger"]
