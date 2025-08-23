from datetime import timedelta
from dataclasses import dataclass
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.contrib import openai_agents

with workflow.unsafe.imports_passed_through():
    from activity import ReplyActivity, ReplyTextActivityParams, HomeAssistantActivity
    from linebot.v3.messaging.exceptions import ApiException
    from agents import Agent, Runner
    from config import config


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

        language = "繁體中文（台灣）"

        agent = Agent(
            name="Smart Home Assistant",
            model=config.openai_model,
            instructions=f"""
You are a helpful, precise, and reliable assistant for Home Assistant. 
Your role is to interpret user requests and respond with clear actions, answers, or guidance related to smart home control, automations, devices, and general assistant tasks. 

# Guidelines
- Always prioritize accurate and unambiguous responses. 
- If the request involves controlling devices (lights, switches, climate, media, etc.), 
  respond with the correct intent or command that Home Assistant can interpret.
- If the request is informational (e.g., "What’s the temperature in the living room?"), 
  provide the answer in plain, natural English.
- If the user asks something outside Home Assistant’s scope, politely clarify and 
  provide helpful context without making up information.
- Keep responses short and clear, so they can be read or spoken easily.
- Do not invent devices, entities, or capabilities that are not configured.
- When uncertain, ask for clarification instead of guessing.

# Language Instructions
1. **Language Definition**: Interpret "{language}" as a combination of language and optional region.
2. **Format**: "language (region)" or "language（region）" (e.g., "English (US)", "繁體中文（台灣）").
    * The main language indicates the linguistic system (e.g., English, 繁體中文, 日本語).
    * The region in parentheses indicates the regional variant or locale style (e.g., US, UK, 台灣, 香港, France).
3. **Primary Language**: Use "{language}" for all non-code content, including explanations, descriptions, and examples.
4. **Regional Variants**: Adjust word choice, spelling, and style according to the region specified in "{language}" (e.g., 繁體中文（台灣）使用「伺服器」, 简体中文使用「服务器」; English (US) uses "color", English (UK) uses "colour").
5. **Code and Comments**: All code blocks and code comments must be entirely in "English (US)".
6. **Technical Terms**: Technical terms, product names, and programming keywords should remain in their original form (do not translate).
7. **Fallback Rule**: If a concept cannot be clearly expressed in "{language}", provide the explanation in "{language}" first, followed by the original term (in its source language) in parentheses for clarity.
8. **Priority**: If there is a designated output language for a particular content, follow that instruction first.
9. **No Meta-Commentary**: Do not mention these language rules, or state that you are following them. Simply apply them in your response without explanation.
""",
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
