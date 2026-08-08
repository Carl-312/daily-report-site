import requests

from utils.enrichment_transport import classify_request_outcome


def http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(response=response)


def test_usage_limit_http_statuses_have_a_terminal_diagnostic() -> None:
    assert classify_request_outcome(http_error(432)) == "usage_limit_exceeded"
    assert classify_request_outcome(http_error(433)) == "usage_limit_exceeded"
    assert classify_request_outcome(http_error(500)) == "http_error"
