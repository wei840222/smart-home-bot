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

    @property
    def langsmith(self) -> LangSmithConfig:
        if self._langsmith_config is None:
            self._langsmith_config = LangSmithConfig()
            os.environ["LANGSMITH_TRACING"] = "true"
            os.environ["LANGSMITH_ENDPOINT"] = self.langsmith.endpoint
            os.environ["LANGSMITH_PROJECT"] = self.langsmith.project or ""
            os.environ["LANGSMITH_API_KEY"] = self.langsmith.api_key or ""
        return self._langsmith_config

    _langsmith_client: Optional[LangSmith] = None

    def get_langsmith_client(self) -> LangSmith:
        if not self.langsmith.enabled:
            raise RuntimeError("LangSmith is not enabled")

        if self._langsmith_client is None:
            self._langsmith_client = LangSmith(
                api_url=self.langsmith.endpoint,
                api_key=self.langsmith.api_key,
            )

        return self._langsmith_client
