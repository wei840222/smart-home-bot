from typing import List

from pydantic.dataclasses import dataclass
from temporalio import activity
from linebot.v3.messaging import (
    AsyncMessagingApi,
    ReplyMessageRequest,
    TextMessage,
    QuickReply,
    QuickReplyItem,
    MessageAction,
    AudioMessage,
)

from config import config

logger = config.logger.get(__name__)


@dataclass
class ReplyTokenParams:
    reply_token: str


@dataclass
class ReplyTextActivityParams(ReplyTokenParams):
    quote_token: str
    message: str


@dataclass
class ReplyQuickReplyActivityParams(ReplyTokenParams):
    quote_token: str
    message: str
    quick_messages: List[str]


@dataclass
class ReplyAudioActivityParams(ReplyTokenParams):
    content_url: str
    duration: int


class ReplyActivity:
    def __init__(self, line_messaging_api: AsyncMessagingApi):
        self.line_messaging_api = line_messaging_api

    @activity.defn(name="ReplyTextActivity")
    async def reply_text(self, input: ReplyTextActivityParams) -> dict:
        response = await self.line_messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=input.reply_token,
                messages=[
                    TextMessage(
                        quote_token=input.quote_token,
                        text=input.message,
                    )
                ],
            )
        )
        logger.info(
            "Reply text message sent successfully.", extra={"response": response}
        )
        return response.to_dict()

    @activity.defn(name="ReplyQuickReplyActivity")
    async def reply_quick_reply(self, input: ReplyQuickReplyActivityParams) -> dict:
        response = await self.line_messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=input.reply_token,
                messages=[
                    TextMessage(
                        quote_token=input.quote_token,
                        text=input.message,
                        quick_reply=QuickReply(
                            items=[
                                QuickReplyItem(
                                    action=MessageAction(label=text, text=text)
                                )
                                for text in input.quick_messages
                            ]
                        ),
                    )
                ],
            )
        )
        logger.info(
            "Reply audio message sent successfully.", extra={"response": response}
        )
        return response.to_dict()

    @activity.defn(name="ReplyAudioActivity")
    async def reply_audio(self, input: ReplyAudioActivityParams) -> dict:
        response = await self.line_messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=input.reply_token,
                messages=[
                    AudioMessage(
                        original_content_url=input.content_url, duration=input.duration
                    )
                ],
            )
        )
        logger.info(
            "Reply audio message sent successfully.", extra={"response": response}
        )
        return response.to_dict()
