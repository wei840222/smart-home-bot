import logging
from typing import Optional, AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from linebot.v3.messaging import AsyncApiClient, AsyncMessagingApi, Configuration
from linebot.v3.webhook import WebhookParser

logger = logging.getLogger(__name__)


class LINEMessagingAPIConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LINE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    channel_secret: str = Field(description="The secret key for the LINE channel.")

    channel_access_token: str = Field(
        description="The access token for the LINE  channel."
    )

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[AsyncMessagingApi, None]:
        async with AsyncApiClient(
            Configuration(access_token=self.channel_access_token)
        ) as client:
            logger.info("Created LINE Messaging API client.")
            yield AsyncMessagingApi(client)
        logger.info("Closed LINE Messaging API client.")

    _webhook_parser: Optional[WebhookParser] = None

    @contextmanager
    def webhook_parser(self) -> Generator[WebhookParser, None]:
        if self._webhook_parser is None:
            self._webhook_parser = WebhookParser(self.channel_secret)
            logger.info("Created LINE Webhook Parser.")
        yield self._webhook_parser


class LINEMessagingAPIConfigMixin:
    _line_messaging_api_config: Optional[LINEMessagingAPIConfig] = None

    @property
    def line(self) -> LINEMessagingAPIConfig:
        if self._line_messaging_api_config is None:
            self._line_messaging_api_config = LINEMessagingAPIConfig()
        return self._line_messaging_api_config
