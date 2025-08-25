import os
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from langsmith import Client as LangSmith

_langsmith_client: Optional[LangSmith] = None


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

    def get_langsmith_client(self) -> LangSmith:
        if not self.enabled:
            raise RuntimeError("LangSmith is not enabled")

        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_ENDPOINT"] = self.endpoint
        os.environ["LANGSMITH_PROJECT"] = self.project  # type: ignore
        os.environ["LANGSMITH_API_KEY"] = self.api_key  # type: ignore

        global _langsmith_client
        if _langsmith_client is None:
            _langsmith_client = LangSmith(
                api_url=self.endpoint, api_key=self.api_key)

        return _langsmith_client
