import logging
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import homeassistant_api

logger = logging.getLogger(__name__)


class HomeAssistantConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HOMEASSISTANT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_url: str = Field(
        default="http://homeassistant.local:8123/api",
        description="The Home Assistant API URL.",
    )

    token: str = Field(default="", description="The Home Assistant API token.")

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[homeassistant_api.Client, None]:
        async with homeassistant_api.Client(
            api_url=self.api_url,
            token=self.token,
            use_async=True,
        ) as client:
            logger.info("Connected to Home Assistant API.")
            yield client
        logger.info("Disconnected from Home Assistant API.")


class HomeAssistantMixin:
    _home_assistant_config: Optional[HomeAssistantConfig] = None

    @property
    def home_assistant(self) -> HomeAssistantConfig:
        if self._home_assistant_config is None:
            self._home_assistant_config = HomeAssistantConfig()
        return self._home_assistant_config
