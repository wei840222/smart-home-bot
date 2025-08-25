from datetime import timedelta

from pydantic.dataclasses import dataclass
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.contrib import openai_agents

with workflow.unsafe.imports_passed_through():
    from activity import ReplyActivity, ReplyTextActivityParams, HomeAssistantActivity
    from linebot.v3.messaging.exceptions import ApiException
    from langchain_core.prompts import PromptTemplate
    from agents import Agent, Runner

    from config import config, logger


@dataclass
class HandleTextMessageWorkflowParams:
    reply_token: str
    quote_token: str
    message: str


@workflow.defn(name="HandleTextMessage")
class HandleTextMessageWorkflow:
    @workflow.run
    async def run(self, input: HandleTextMessageWorkflowParams) -> bool:
        retry_policy = RetryPolicy(
            maximum_attempts=3,
            maximum_interval=timedelta(seconds=5),
            non_retryable_error_types=[ApiException.__name__],
        )

        prompt_template = PromptTemplate.from_template("\n\n".join([
            config.get_prompt("system_prompt").text,
            config.get_prompt("language_prompt").text,
        ]))

        agent = Agent(
            name="Smart Home Assistant",
            model=config.openai_model,
            instructions=prompt_template.format(language="繁體中文（台灣）"),
            tools=[
                openai_agents.workflow.activity_as_tool(
                    HomeAssistantActivity.remote_control_air_conditioner,
                    start_to_close_timeout=timedelta(seconds=5)
                )
            ],
        )

        result = await Runner.run(agent, input=input.message)

        await workflow.execute_activity(
            ReplyActivity.reply_text,  # type: ignore
            ReplyTextActivityParams(
                reply_token=input.reply_token,
                quote_token=input.quote_token,
                message=result.final_output,
            ),
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy=retry_policy,
        )

        return True
