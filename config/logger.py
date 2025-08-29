import sys
import time
import logging
from typing import Optional, List

import structlog
from structlog.types import EventDict, Processor
from structlog.stdlib import ProcessorFormatter
from pydantic_settings import BaseSettings, SettingsConfigDict
from fastapi import FastAPI, Request, Response, status
from asgi_correlation_id.context import correlation_id
from asgi_correlation_id import CorrelationIdMiddleware
from uvicorn.protocols.utils import get_path_with_query_string


class LoggerConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    level: str = "info"
    format: str = "console"

    # https://github.com/hynek/structlog/issues/35#issuecomment-591321744
    def _rename_event_key(self, _, event_dict: EventDict) -> EventDict:
        """
        Log entries keep the text message in the `event` field, but Datadog
        uses the `message` field. This processor moves the value from one field to
        the other.
        See https://github.com/hynek/structlog/issues/35#issuecomment-591321744
        """
        event_dict["message"] = event_dict.pop("event")
        return event_dict

    def _drop_color_message_key(self, _, event_dict: EventDict) -> EventDict:
        """
        Uvicorn logs the message a second time in the extra `color_message`, but we don't
        need it. This processor drops the key from the event dict if it exists.
        """
        event_dict.pop("color_message", None)
        return event_dict

    def _get_structlog_formatter(self) -> ProcessorFormatter:
        timestamper = structlog.processors.TimeStamper(fmt="iso")

        shared_processors: List[Processor] = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.stdlib.ExtraAdder(),
            LoggerConfig._drop_color_message_key,
            timestamper,
            structlog.processors.StackInfoRenderer(),
        ]

        if self.format.lower() == "json":
            # We rename the `event` key to `message` only in JSON logs, as Datadog looks for the
            # `message` key but the pretty ConsoleRenderer looks for `event`
            shared_processors.append(LoggerConfig._rename_event_key)
            # Format the exception only for JSON logs, as we want to pretty-print them when
            # using the ConsoleRenderer
            shared_processors.append(structlog.processors.format_exc_info)

        structlog.configure(
            processors=shared_processors
            + [
                # Prepare event dict for `ProcessorFormatter`.
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        log_renderer: structlog.types.Processor
        if self.format.lower() == "json":
            log_renderer = structlog.processors.JSONRenderer()
        else:
            log_renderer = structlog.dev.ConsoleRenderer()

        return structlog.stdlib.ProcessorFormatter(
            # These run ONLY on `logging` entries that do NOT originate within
            # structlog.
            foreign_pre_chain=shared_processors,
            # These run on ALL entries after the pre_chain is done.
            processors=[
                # Remove _record & _from_structlog.
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                log_renderer,
            ],
        )

    def configure_granian_loggers(self):
        # Clear the log handlers for uvicorn loggers, and enable propagation
        # so the messages are caught by our root logger and formatted correctly
        # by structlog
        logging.getLogger("_granian").handlers.clear()
        logging.getLogger("_granian").propagate = True

    def configure_fastapi_loggers(self, app: FastAPI):
        error_logger = self.get("fastapi.error")
        access_logger = self.get("fastapi.access")

        async def logging_middleware(request: Request, call_next) -> Response:
            structlog.contextvars.clear_contextvars()
            # These context vars will be added to all log entries emitted during the request
            request_id = correlation_id.get()
            structlog.contextvars.bind_contextvars(request_id=request_id)

            start_time = time.perf_counter_ns()
            # If the call_next raises an error, we still want to return our own 500 response,
            # so we can add headers to it (process time, request ID...)
            response = Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
            try:
                response = await call_next(request)
            except Exception:
                # TODO: Validate that we don't swallow exceptions (unit test?)
                error_logger.exception("Uncaught exception")
                raise
            finally:
                process_time = time.perf_counter_ns() - start_time
                status_code = response.status_code
                url = get_path_with_query_string(request.scope)  # type: ignore
                client_host = request.client.host  # type: ignore
                client_port = request.client.port  # type: ignore
                http_method = request.method
                http_version = request.scope["http_version"]
                # Recreate the Uvicorn access log format, but add all parameters as structured information
                message = f"""{client_host}:{client_port} - "{http_method} {url} HTTP/{http_version}" {status_code} {process_time / 10.0**6}ms"""
                extra = {
                    "http": {
                        "url": str(request.url),
                        "status_code": status_code,
                        "method": http_method,
                        "request_id": request_id,
                        "version": http_version,
                    },
                    "network": {"client": {"ip": client_host, "port": client_port}},
                    "duration": process_time,
                }

                match status_code:
                    case code if (
                        status.HTTP_400_BAD_REQUEST
                        <= code
                        < status.HTTP_500_INTERNAL_SERVER_ERROR
                    ):
                        access_logger.warning(message, extra=extra)
                    case code if code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
                        access_logger.error(message, extra=extra)
                    case _:
                        access_logger.info(message, extra=extra)

                # seconds
                response.headers["X-Process-Time"] = str(process_time / 10.0**9)
                return response

        app.middleware("http")(logging_middleware)

        # This middleware must be placed after the logging, to populate the context with the request ID
        # NOTE: Why last??
        # Answer: middlewares are applied in the reverse order of when they are added (you can verify this
        # by debugging `app.middleware_stack` and recursively drilling down the `app` property).
        app.add_middleware(CorrelationIdMiddleware)

    _logger: Optional[logging.Logger] = None

    def get(self, name: Optional[str] = None) -> logging.Logger:
        """
        Get a logger with the specified name, configured with the settings from this config.
        """
        if self._logger is None:
            handler = logging.StreamHandler()
            # Use OUR `ProcessorFormatter` to format all `logging` entries.
            handler.setFormatter(self._get_structlog_formatter())

            self._logger = logging.getLogger()
            self._logger.addHandler(handler)
            self._logger.setLevel(self.level.upper())

            def handle_exception(exc_type, exc_value, exc_traceback):
                """
                Log any uncaught exception instead of letting it be printed by Python
                (but leave KeyboardInterrupt untouched to allow users to Ctrl+C to stop)
                See https://stackoverflow.com/a/16993115/3641865
                """
                if issubclass(exc_type, KeyboardInterrupt):
                    sys.__excepthook__(exc_type, exc_value, exc_traceback)
                    return

                self._logger.error(  # type: ignore
                    "Uncaught exception",
                    exc_info=(
                        exc_type,
                        exc_value,
                        exc_traceback,
                    ),
                )

            sys.excepthook = handle_exception

        if name is None:
            return self._logger

        logger = logging.getLogger(name)
        logger.setLevel(self.level.upper())
        return logger


class LoggerMixin:
    _logger_config: Optional[LoggerConfig] = None

    @property
    def logger(self) -> LoggerConfig:
        if self._logger_config is None:
            self._logger_config = LoggerConfig()
        return self._logger_config
