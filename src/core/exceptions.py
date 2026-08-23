"""Safe questionnaire API errors that never expose private model instructions."""

class QuestionnaireError(Exception):
    """Base exception with a safe public response."""

    status_code = 500
    error_code = "questionnaire_error"
    public_message = "The questionnaire request could not be completed."


class QuestionnaireConfigurationNotFound(QuestionnaireError):
    """Raised when the requested questionnaire configuration does not exist."""

    status_code = 404
    error_code = "questionnaire_configuration_not_found"
    public_message = "The requested questionnaire configuration was not found."


class QuestionnaireConfigurationInvalid(QuestionnaireError):
    """Raised when the external questionnaire configuration is not valid."""

    status_code = 500
    error_code = "questionnaire_configuration_invalid"
    public_message = "The questionnaire configuration could not be loaded."


class QuestionnaireRunNotFound(QuestionnaireError):
    """Raised when a questionnaire run identifier does not exist."""

    status_code = 404
    error_code = "questionnaire_run_not_found"
    public_message = "The requested questionnaire run was not found."


class QuestionnaireRequestConflict(QuestionnaireError):
    """Raised when a request conflicts with previously submitted data."""

    status_code = 409
    error_code = "questionnaire_request_conflict"
    public_message = "The questionnaire request conflicts with an existing request."


class QuestionnaireProviderUnavailable(QuestionnaireError):
    """Raised when all configured model providers are temporarily unavailable."""

    status_code = 503
    error_code = "questionnaire_provider_unavailable"
    public_message = "The questionnaire service is temporarily unavailable."
