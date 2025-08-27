import signal
import asyncio
from typing import Annotated, List

import uvicorn
from fastapi import FastAPI, Header, Request, HTTPException, status
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
    logger = config.logger.get("handler.callback.line")

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


def graceful_shutdown(sig: signal.Signals, task_to_cancel: set[asyncio.Task]) -> None:
    logger.info("received exit signal", extra={"signal": sig.name})
    for task in task_to_cancel:
        logger.info("cancelling task", extra={"task": task})
        task.cancel()


async def main() -> None:
    try:
        async with (
            config.temporal.connect() as temporal_client,
            config.mqtt.connect() as mqtt_client,
            config.line.connect() as line_messaging_api_client,
        ):
            home_assistant_activity = HomeAssistantActivity(mqtt_client)
            reply_activity = ReplyActivity(line_messaging_api_client)

            worker = TemporalWorker(
                temporal_client,
                task_queue=config.temporal.task_queue,
                workflows=[HandleTextMessageWorkflow],
                activities=[
                    reply_activity.reply_text,
                    reply_activity.reply_quick_reply,
                    reply_activity.reply_audio,
                    home_assistant_activity.remote_control_air_conditioner,
                ],
            )
            asyncio.create_task(worker.run())
            logger.info(
                "Temporal worker started.",
                extra={"task_queue": config.temporal.task_queue},
            )
            await uvicorn.Server(
                uvicorn.Config(app, host="0.0.0.0", port=8000, log_config=None)
            ).serve()
    except asyncio.exceptions.CancelledError:
        logger.info("Uvicorn server cancelled, shutting down...")
    finally:
        await worker.shutdown()
        logger.info("Temporal worker shutdown successfully.")


if __name__ == "__main__":
    config.logger.configure_uvicorn_loggers()
    config.logger.configure_fastapi_loggers(app)
    asyncio.run(main())
