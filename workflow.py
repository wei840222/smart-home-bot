from datetime import timedelta
from typing import Any, List

from pydantic import Field
from pydantic.dataclasses import dataclass
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.contrib import openai_agents

with workflow.unsafe.imports_passed_through():
    from activity import ReplyActivity, ReplyTextActivityParams, HomeAssistantActivity
    from linebot.v3.messaging.exceptions import ApiException
    from langchain_core.prompts import PromptTemplate
    from agents import (
        Agent,
        GuardrailFunctionOutput,
        InputGuardrail,
        InputGuardrailTripwireTriggered,
        Runner,
        RunContextWrapper,
        TContext,
        TResponseInputItem,
        set_trace_processors,
    )
    from langsmith.wrappers import OpenAIAgentsTracingProcessor

    from config import config

    logger = config.logger.get("temporal.workflow")

    if config.langsmith.enabled:
        logger.info("LangSmith integration is enabled.")
        set_trace_processors(
            [OpenAIAgentsTracingProcessor(client=config.get_langsmith_client())]
        )


@dataclass
class HandleTextMessageWorkflowParams:
    reply_token: str
    quote_token: str
    message: str


@workflow.defn(name="HandleTextMessage", sandboxed=False)
class HandleTextMessageWorkflow:
    async def _input_guardrail(
        self,
        ctx: RunContextWrapper[TContext],
        _: Agent[Any],
        input_data: str | List[TResponseInputItem],
    ):
        @dataclass
        class InputGuardrailOutput:
            is_related: bool = Field(
                description="Whether the input is related to smart home."
            )
            is_supported: bool = Field(
                description="Whether the input is within the supported use cases."
            )
            reason: str = Field(description="Reasoning for the determination.")

        guardrail_agent = Agent(
            name="Smart Home Input Guardrail",
            instructions=config.get_prompt("input-guardrail-prompt").text,
            output_type=InputGuardrailOutput,
        )

        result = await Runner.run(guardrail_agent, input_data, context=ctx.context)
        final_output = result.final_output_as(InputGuardrailOutput)

        return GuardrailFunctionOutput(
            output_info=final_output,
            tripwire_triggered=(not final_output.is_related)
            or (not final_output.is_supported),
        )

    @workflow.run
    async def run(self, input: HandleTextMessageWorkflowParams) -> bool:
        retry_policy = RetryPolicy(
            maximum_attempts=3,
            maximum_interval=timedelta(seconds=5),
            non_retryable_error_types=[ApiException.__name__],
        )

        prompt_template = PromptTemplate.from_template(
            "\n\n".join(
                [
                    config.get_prompt("system-prompt").text,
                    config.get_prompt("language-prompt").text,
                ]
            )
        )

        agent = Agent(
            name="Smart Home Assistant",
            model=config.openai_model,
            instructions=prompt_template.format(language="繁體中文（台灣）"),
            tools=[
                openai_agents.workflow.activity_as_tool(
                    HomeAssistantActivity.remote_control_air_conditioner,
                    start_to_close_timeout=timedelta(seconds=5),
                )
            ],
            input_guardrails=[
                InputGuardrail(guardrail_function=self._input_guardrail),
            ],
        )

        try:
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

        except InputGuardrailTripwireTriggered as error:
            logger.warning(
                "Input guardrail triggered.",
                extra={
                    "input": input.message,
                    "output": error.guardrail_result.output.output_info,
                    "error": error,
                },
            )
            await workflow.execute_activity(
                ReplyActivity.reply_text,  # type: ignore
                ReplyTextActivityParams(
                    reply_token=input.reply_token,
                    quote_token=input.quote_token,
                    message="很抱歉，我只能處理與智慧家庭相關的請求。"
                    if not error.guardrail_result.output.output_info.is_related
                    else "很抱歉，我只能處理支援的請求。",
                ),
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=retry_policy,
            )
            return False
