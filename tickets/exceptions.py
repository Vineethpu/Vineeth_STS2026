from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    if isinstance(detail, dict) and "detail" in detail:
        message = detail["detail"]
        errors = None
    else:
        message = "Request failed. Please check the supplied data."
        errors = detail

    response.data = {
        "success": False,
        "message": str(message),
        "errors": errors,
    }
    return response
