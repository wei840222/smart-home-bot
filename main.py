import time
import socket
import logging
import asyncio
import uvicorn
import structlog
from typing import Annotated
from datetime import timedelta
from contextlib import asynccontextmanager
from asgi_correlation_id.context import correlation_id
from asgi_correlation_id import CorrelationIdMiddleware
from uvicorn.protocols.utils import get_path_with_query_string
from fastapi import FastAPI, Header, Request, Response, HTTPException, status
from temporalio.client import Client as TemporalClient
from temporalio.common import WorkflowIDReusePolicy
from temporalio.worker import Worker as TemporalWorker
from temporalio.contrib.openai_agents import OpenAIAgentsPlugin, ModelActivityParameters

from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
)
from linebot.v3.webhook import WebhookParser
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

from paho.mqtt import enums as mqtt_enums
from paho.mqtt import client as mqtt

from config import config, logger
from workflow import HandleTextMessageWorkflow, HandleTextMessageWorkflowParams
from activity import ReplyActivity, HomeAssistantActivity


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = await TemporalClient.connect(config.temporal_address, namespace=config.temporal_namespace, plugins=[
        OpenAIAgentsPlugin(
            model_params=ModelActivityParameters(
                start_to_close_timeout=timedelta(seconds=30)
            )
        ),
    ])
    app.state.temporal_client = client
    logger.info("Connected to Temporal server.", extra={
        "address": config.temporal_address, "namespace": config.temporal_namespace})

    line_messaging_api = AsyncMessagingApi(AsyncApiClient(Configuration(
        access_token=config.line_channel_access_token)))

    mqtt_client = mqtt.Client(client_id=socket.gethostname(),
                              protocol=mqtt_enums.MQTTProtocolVersion.MQTTv5,
                              callback_api_version=mqtt_enums.CallbackAPIVersion.VERSION2)
    mqtt_client.username_pw_set(config.mqtt_user, config.mqtt_password)

    def mqtt_on_connect(_, userdata, flags, rc, properties):
        if rc != 0:
            raise ConnectionError(
                f"Failed to connect to MQTT Broker, return code {rc}")
        logger.info("Connected to MQTT Broker!", extra={
            "userdata": userdata,
            "flags": flags,
            "properties": properties
        })
    mqtt_client.on_connect = mqtt_on_connect
    mqtt_client.connect(config.mqtt_broker, config.mqtt_port)
    mqtt_client.loop_start()

    reply_activity = ReplyActivity(line_messaging_api)
    home_assistant_activity = HomeAssistantActivity(mqtt_client)

    worker = TemporalWorker(
        client,
        task_queue=config.temporal_task_queue,
        workflows=[HandleTextMessageWorkflow],
        activities=[reply_activity.reply_text,
                    reply_activity.reply_quick_reply,
                    reply_activity.reply_audio,
                    home_assistant_activity.remote_control_air_conditioner],
    )

    task = asyncio.create_task(worker.run())
    logger.info("Temporal worker started.", extra={
                "task_queue": config.temporal_task_queue})

    yield

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        await worker.shutdown()
        logger.info(
            "Application shutdown: Temporal worker shutdown gracefully.")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        logger.info("Application shutdown: MQTT client disconnected.")
        await line_messaging_api.api_client.close()
        logger.debug("Application shutdown: LINE API Client closed.")

app = FastAPI(lifespan=lifespan, docs_url=None,
              redoc_url=None, openapi_url=None)

access_logger = logging.getLogger("fastapi.access")


@app.middleware("http")
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
        logging.getLogger("fastapi.error").exception("Uncaught exception")
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
        message = f"""{client_host}:{client_port} - "{http_method} {url} HTTP/{http_version}" {status_code} {process_time / 10.0 ** 6}ms"""
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
            case code if 400 <= code < 500:
                access_logger.warning(message, extra=extra)
            case code if code >= 500:
                access_logger.error(message, extra=extra)
            case _:
                access_logger.info(message, extra=extra)

        # seconds
        response.headers["X-Process-Time"] = str(process_time / 10.0 ** 9)
        return response

# This middleware must be placed after the logging, to populate the context with the request ID
# NOTE: Why last??
# Answer: middlewares are applied in the reverse order of when they are added (you can verify this
# by debugging `app.middleware_stack` and recursively drilling down the `app` property).
app.add_middleware(CorrelationIdMiddleware)


@app.get("/health")
def health():
    return "OK"


@app.post("/callback", status_code=status.HTTP_202_ACCEPTED)
async def handle_callback(request: Request, x_line_signature: Annotated[str, Header()]):
    body = await request.body()

    try:
        events = WebhookParser(config.line_channel_secret).parse(
            body.decode(), x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature.")

    temporal_client: TemporalClient = app.state.temporal_client

    for event in events:  # type: ignore
        logger.debug("Received webhook event.", extra={"event": event})
        if not isinstance(event, MessageEvent):
            continue
        if not isinstance(event.message, TextMessageContent):
            continue

        handle = await temporal_client.start_workflow(
            HandleTextMessageWorkflow.run,
            HandleTextMessageWorkflowParams(
                reply_token=event.reply_token,  # type: ignore
                quote_token=event.message.quote_token,
                message=event.message.text
            ),
            id=event.webhook_event_id,
            task_queue=config.temporal_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.TERMINATE_IF_RUNNING,
        )
        logger.info("Started workflow for handling text message.", extra={
                    "task_queue": config.temporal_task_queue, "workflow_id": handle.id})

    return "ACCEPTED"

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)
