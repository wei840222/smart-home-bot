import os
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from langsmith import Client as LangSmith


class LangSmithConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LANGSMITH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    endpoint: str = "https://api.smith.langchain.com"
    project: Optional[str] = None
    api_key: Optional[str] = None
    environment: str = "local"
    release: str = "nightly"
    version: str = "0.0.0"

    @property
    def enabled(self) -> bool:
        return self.project is not None and self.api_key is not None


class LangSmithMixin:
    _langsmith_config: Optional[LangSmithConfig] = None
    _langsmith_client: Optional[LangSmith] = None

    def get_langsmith_client(self) -> LangSmith:
        if self._langsmith_config is None:
            self._langsmith_config = LangSmithConfig()
        if not self._langsmith_config.enabled:
            raise RuntimeError("LangSmith is not enabled")

        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_ENDPOINT"] = self._langsmith_config.endpoint
        os.environ["LANGSMITH_PROJECT"] = self._langsmith_config.project or ""
        os.environ["LANGSMITH_API_KEY"] = self._langsmith_config.api_key or ""

        if self._langsmith_client is None:
            self._langsmith_client = LangSmith(
                api_url=self._langsmith_config.endpoint,
                api_key=self._langsmith_config.api_key,
            )

        return self._langsmith_client
