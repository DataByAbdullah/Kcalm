"""Capability catalog; configuration is not proof of a provider connection."""
from dataclasses import dataclass


@dataclass(frozen=True)
class IntegrationDefinition:
    code: str
    name: str
    capabilities: tuple[str, ...]
    implemented: bool
    required_settings: tuple[str, ...] = ()


INTEGRATIONS = (
    IntegrationDefinition("usda", "USDA FoodData Central", ("food_search", "food_import"), True, ("usda_api_key",)),
    IntegrationDefinition("openai", "OpenAI", ("constraint_interpretation",), True, ("openai_api_key",)),
    IntegrationDefinition("smtp", "SMTP email", ("password_reset_email",), True, ("smtp_host", "smtp_from_email")),
    IntegrationDefinition("wearable_sync", "Wearable sync", ("steps_import",), False),
    IntegrationDefinition("grocery_delivery", "Grocery delivery", ("grocery_order",), False),
    IntegrationDefinition("push_notifications", "Push notifications", ("device_notifications",), False),
)
