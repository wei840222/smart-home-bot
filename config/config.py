from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .logger import LoggerMixin
from .prompt import PromptMixin
from .temporal import TemporalMixin
from .mqtt import MQTTMixin
from .homeassistant import HomeAssistantMixin
from .line import LINEMessagingAPIConfigMixin


class Config(
    BaseSettings,
    LoggerMixin,
    PromptMixin,
    TemporalMixin,
    MQTTMixin,
    HomeAssistantMixin,
    LINEMessagingAPIConfigMixin,
):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = Field(description="The API key for OpenAI.")
    openai_model: str = Field(
        default="gpt-5-mini", description="The OpenAI model to use for the assistant."
    )
