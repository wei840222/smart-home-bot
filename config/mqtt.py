import socket
import logging
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import aiomqtt

logger = logging.getLogger(__name__)


class MQTTConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MQTT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    broker: str = Field(default="localhost", description="The MQTT broker address.")

    port: int = Field(default=1883, description="The MQTT broker port.")

    user: str = Field(
        default="smart-home-bot", description="The username for the MQTT connection."
    )

    password: str = Field(
        default="", description="The password for the MQTT connection."
    )

    identifier: str = Field(
        default=socket.gethostname(), description="The identifier for the MQTT client."
    )

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[aiomqtt.Client, None]:
        async with aiomqtt.Client(
            hostname=self.broker,
            port=self.port,
            username=self.user,
            password=self.password,
            identifier=self.identifier,
            protocol=aiomqtt.ProtocolVersion.V5,
            logger=logger,
        ) as client:
            logger.info(
                "Connected to MQTT broker.",
                extra={
                    "broker": self.broker,
                    "port": self.port,
                    "username": self.user,
                    "client_id": self.identifier,
                },
            )
            yield client
        logger.info("Disconnected from MQTT broker.")


class MQTTMixin:
    _mqtt_config: Optional[MQTTConfig] = None

    @property
    def mqtt(self) -> MQTTConfig:
        if self._mqtt_config is None:
            self._mqtt_config = MQTTConfig()
        return self._mqtt_config
