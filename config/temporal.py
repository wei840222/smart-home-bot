import logging
from datetime import timedelta
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from temporalio.client import Client as TemporalClient
from temporalio.contrib.openai_agents import OpenAIAgentsPlugin, ModelActivityParameters


class TemporalConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TEMPORAL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    address: str = Field(
        default="localhost:7233",
        description="The address of the Temporal frontend server.",
    )

    namespace: str = Field(
        default="default", description="The namespace for the Temporal workflows."
    )

    task_queue: str = Field(
        default="BOT_FARM:SMART_HOME_BOT",
        description="The task queue for the Temporal worker.",
    )

    _client: Optional[TemporalClient] = None

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[TemporalClient, None]:
        if self._client is None:
            self._client = await TemporalClient.connect(
                self.address,
                namespace=self.namespace,
                plugins=[
                    OpenAIAgentsPlugin(
                        model_params=ModelActivityParameters(
                            start_to_close_timeout=timedelta(seconds=30)
                        )
                    )
                ],
            )
            logging.getLogger("temporal").info(
                "Connected to Temporal server.",
                extra={"address": self.address, "namespace": self.namespace},
            )
        yield self._client


class TemporalMixin:
    _temporal_config: Optional[TemporalConfig] = None

    @property
    def temporal(self) -> TemporalConfig:
        if self._temporal_config is None:
            self._temporal_config = TemporalConfig()
        return self._temporal_config
