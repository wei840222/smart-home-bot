import socket

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .logger import LoggerMixin
from .prompt import PromptMixin


class Config(BaseSettings, LoggerMixin, PromptMixin):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    hostname: str = Field(
        default=socket.gethostname(),
        description="The hostname of the machine."
    )

    line_channel_secret: str = Field(
        description="The secret key for the LINE channel.")

    line_channel_access_token: str = Field(
        description="The access token for the LINE  channel.")

    openai_api_key: str = Field(description="The API key for OpenAI.")
    openai_model: str = Field(
        default="gpt-5-mini",
        description="The OpenAI model to use for the assistant.")

    temporal_address: str = Field(
        default="localhost:7233",
        description="The address of the Temporal frontend server.")

    temporal_namespace: str = Field(
        default="default",
        description="The namespace for the Temporal workflows.")

    temporal_task_queue: str = Field(
        default="BOT_FARM:SMART_HOME_BOT",
        description="The task queue for the Temporal worker.")

    mqtt_broker: str = Field(
        default="localhost",
        description="The MQTT broker address.")

    mqtt_port: int = Field(
        default=1883,
        description="The MQTT broker port.")

    mqtt_user: str = Field(
        default="smart-home-bot",
        description="The username for the MQTT connection.")

    mqtt_password: str = Field(
        default="",
        description="The password for the MQTT connection.")
