from app.core.exceptions import APIErrorException
from app.integrations.registry import INTEGRATIONS
from app.schemas.integration import IntegrationStatusResponse


def integration_status(definition, settings):
    status = "not_implemented"
    if definition.implemented:
        status = "configured" if all(bool(getattr(settings, key, None)) for key in definition.required_settings) else "not_configured"
    return IntegrationStatusResponse(code=definition.code, name=definition.name,
                                      capabilities=list(definition.capabilities), status=status)


def list_integrations(settings):
    return [integration_status(definition, settings) for definition in INTEGRATIONS]


def get_integration(code, settings):
    definition = next((item for item in INTEGRATIONS if item.code == code), None)
    if definition is None:
        raise APIErrorException(404, "INTEGRATION_NOT_FOUND", "Integration not found.")
    return integration_status(definition, settings)
