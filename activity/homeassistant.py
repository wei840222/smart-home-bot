import json

from pydantic import Field
from pydantic.dataclasses import dataclass
from temporalio import activity

import aiomqtt
import homeassistant_api

from config import config

logger = config.logger.get(__name__)


@dataclass
class RemoteControlAirConditionerActivityParams:
    power_on: bool = Field(
        default=True, description="Power on or off the air conditioner."
    )
    temperature: int = Field(
        default=25, ge=16, le=32, description="Set temperature. In Celsius."
    )


class HomeAssistantActivity:
    def __init__(
        self,
        mqtt_client: aiomqtt.Client,
        home_assistant_client: homeassistant_api.Client,
    ):
        self.mqtt_client = mqtt_client
        self.home_assistant_client = home_assistant_client

    @activity.defn(name="Check1FInnerDoorStatusActivity")
    async def check_1f_inner_door_status(self) -> str:
        """
        Check the status of the 1F inner door sensor.
        "on" means the door is opened, "off" means the door is closed, "unknown" means the state is not available.

        Returns:
            str: The state of the binary sensor (ex: "on", "off" or "unknown").
        """
        result = await self.home_assistant_client.async_get_state(
            entity_id="binary_sensor.1f_inner_door_contact"
        )
        return result.state

    @activity.defn(name="Check2FBedroomPresenceStatusActivity")
    async def check_2f_bedroom_presence_status(self) -> str:
        """
        Check the status of the 2F bedroom presence sensor.
        "yes" means there is someone present, "no" means no one is present, "unknown" means the state is not available.

        Returns:
            str: The state of the binary sensor (ex: "yes", "no" or "unknown").
        """
        result = await self.home_assistant_client.async_get_state(
            entity_id="binary_sensor.athom_presence_sensor_9bd330_occupancy"
        )
        return (
            "yes"
            if result.state == "on"
            else ("no" if result.state == "off" else result.state)
        )

    @activity.defn(name="RemoteControlAirConditionerActivity")
    async def remote_control_air_conditioner(
        self, input: RemoteControlAirConditionerActivityParams
    ):
        """
        Remote control the air conditioner.

        Args:
            input (RemoteControlAirConditionerActivityParams): The parameters for controlling the air conditioner.
        """

        topic = "tasmota/cmnd/IRHVAC"
        payload = self._generate_mqtt_payload(input.power_on, input.temperature)
        logger.info(
            "Publishing MQTT message to control air conditioner.",
            extra={"topic": topic, "payload": payload},
        )

        await self.mqtt_client.publish(topic=topic, payload=json.dumps(payload), qos=2)

    def _generate_mqtt_payload(self, power_on: bool, temperature: int) -> dict:
        return {
            "Vendor": "HITACHI_AC344",
            "Model": -1,
            "Command": "Control",
            "Mode": "Cool",
            "Power": "On" if power_on else "Off",
            "Celsius": "On",
            "Temp": temperature,
            "FanSpeed": "Auto",
            "SwingV": "Auto",
            "SwingH": "Auto",
        }
