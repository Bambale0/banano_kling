"""HTTP access telemetry without query tokens, signed links or auth headers."""
from aiohttp.abc import AbstractAccessLogger


class PathOnlyAccessLogger(AbstractAccessLogger):
    def log(self, request, response, time):
        self.logger.info('%s %s %s status=%s bytes=%s duration_ms=%.1f',
                         request.remote, request.method, request.path,
                         response.status, response.body_length, time * 1000)
