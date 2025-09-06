import signal
import asyncio
from typing import Annotated, List, Set

from fastapi import FastAPI, Header, Request, HTTPException, status
from granian.server.embed import Server
from granian.constants import Interfaces
from temporalio.common import WorkflowIDReusePolicy
from temporalio.worker import Worker as TemporalWorker
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.webhooks.models import Event

from config import config, logger
from workflow import HandleTextMessageWorkflow, HandleTextMessageWorkflowParams
from activity import ReplyActivity, HomeAssistantActivity


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    return "OK"


@app.post("/callback/line", status_code=status.HTTP_202_ACCEPTED)
async def handle_callback(
    request: Request, x_line_signature: Annotated[str, Header()]
) -> str:
    body = await request.body()

    try:
        with config.line.webhook_parser() as parser:
            events: List[Event] = parser.parse(body.decode(), x_line_signature)  # type: ignore
    except InvalidSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature."
        )

    async with config.temporal.connect() as temporal_client:
        for event in events:
            logger.info("Received webhook event.", extra={"event": event})
            if not isinstance(event, MessageEvent):
                continue
            if not isinstance(event.message, TextMessageContent):
                continue

            handle = await temporal_client.start_workflow(
                HandleTextMessageWorkflow.run,
                HandleTextMessageWorkflowParams(
                    reply_token=event.reply_token,  # type: ignore
                    quote_token=event.message.quote_token,
                    message=event.message.text,
                ),
                id=event.webhook_event_id,
                task_queue=config.temporal.task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.TERMINATE_IF_RUNNING,
            )
            logger.info(
                "Started workflow for handling text message.",
                extra={
                    "task_queue": config.temporal.task_queue,
                    "workflow_id": handle.id,
                },
            )

    return "ACCEPTED"


async def start_server() -> None:
    shutdown_event = asyncio.Event()

    def _signal_handler(sig: signal.Signals) -> None:
        if shutdown_event.is_set():
            return
        logger.info("received exit signal", extra={"signal": sig.name})
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    task_to_cancel: Set[asyncio.Task] = set()

    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler, sig)

    async with (
        config.temporal.connect() as temporal_client,
        config.mqtt.connect() as mqtt_client,
        config.home_assistant.connect() as home_assistant_client,
        config.line.connect() as line_messaging_api_client,
    ):
        home_assistant_activity = HomeAssistantActivity(
            mqtt_client, home_assistant_client
        )
        reply_activity = ReplyActivity(line_messaging_api_client)

        worker = TemporalWorker(
            temporal_client,
            task_queue=config.temporal.task_queue,
            workflows=[HandleTextMessageWorkflow],
            activities=[
                reply_activity.reply_text,
                reply_activity.reply_quick_reply,
                reply_activity.reply_audio,
                home_assistant_activity.check_1f_inner_door_status,
                home_assistant_activity.check_2f_bedroom_presence_status,
                home_assistant_activity.remote_control_air_conditioner,
            ],
        )
        task_to_cancel.add(asyncio.create_task(worker.run()))
        logger.info(
            "Temporal worker started.",
            extra={"task_queue": config.temporal.task_queue},
        )

        server = Server(
            app,
            address="0.0.0.0",
            port=8000,
            interface=Interfaces.ASGI,
        )
        config.logger.configure_granian_loggers()
        config.logger.configure_fastapi_loggers(app)
        task_to_cancel.add(asyncio.create_task(server.serve()))
        logger.info(
            "Granian server started.", extra={"address": "0.0.0.0", "port": 8000}
        )

        await shutdown_event.wait()

    try:
        await asyncio.wait_for(server.shutdown(), timeout=30)
        logger.info("Granian server shutdown successfully.")
        await asyncio.wait_for(worker.shutdown(), timeout=30)
        logger.info("Temporal worker shutdown successfully.")
    except asyncio.TimeoutError:
        logger.warning("Timeout during shutdown, cancelling tasks...")
    finally:
        for task in task_to_cancel:
            cancelled = task.cancel()
            if not cancelled:
                await task
            logger.info("Cancelled task", extra={"task": task, "cancelled": cancelled})


if __name__ == "__main__":
    asyncio.run(start_server())
