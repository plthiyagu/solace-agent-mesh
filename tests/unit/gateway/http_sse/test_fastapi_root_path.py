"""
Unit tests for the fastapi_root_path configuration (issue #1486).

The Web UI gateway can be mounted behind a reverse proxy at a sub-path
(e.g. https://host/agent-mesh/). uvicorn must receive that prefix as
root_path so FastAPI generates correct redirect, docs and absolute URLs.

Covers:
- App schema declares fastapi_root_path with an empty-string default
- Component runtime fallback matches the schema default
- The uvicorn.Config call receives root_path from the component
"""

import inspect
from unittest.mock import MagicMock, patch

from solace_agent_mesh.gateway.http_sse.app import WebUIBackendApp
from solace_agent_mesh.gateway.http_sse.component import WebUIBackendComponent


class TestRootPathSchema:
    def test_app_schema_declares_empty_default(self):
        params = {
            param["name"]: param
            for param in WebUIBackendApp.SPECIFIC_APP_SCHEMA_PARAMS
        }

        assert "fastapi_root_path" in params
        assert params["fastapi_root_path"]["required"] is False
        assert params["fastapi_root_path"]["type"] == "string"
        assert params["fastapi_root_path"]["default"] == ""

    def test_component_runtime_fallback_matches_schema_default(self):
        source = inspect.getsource(WebUIBackendComponent.__init__)

        assert 'self.get_config("fastapi_root_path", "")' in source


class TestRootPathReachesUvicorn:
    def _start_server(self, component):
        with (
            patch(
                "solace_agent_mesh.gateway.http_sse.component.uvicorn.Config"
            ) as mock_config,
            patch("solace_agent_mesh.gateway.http_sse.component.uvicorn.Server"),
            patch("solace_agent_mesh.gateway.http_sse.component.threading.Thread"),
            patch("solace_agent_mesh.gateway.http_sse.component.TaskLoggerService"),
            patch(
                "solace_agent_mesh.gateway.http_sse.component.dependencies"
            ) as mock_deps,
            patch("solace_agent_mesh.gateway.http_sse.component.log"),
            patch(
                "solace_agent_mesh.gateway.http_sse.component.feature_flags"
            ) as mock_ff,
            patch.dict(
                "sys.modules",
                {"solace_agent_mesh.gateway.http_sse.main": MagicMock()},
            ),
        ):
            mock_ff.get_registry.return_value.keys.return_value = []
            mock_deps.SessionLocal = None
            WebUIBackendComponent._start_fastapi_server(component)
        return mock_config

    def _component(self) -> MagicMock:
        component = MagicMock()
        component.fastapi_app = None
        component.fastapi_thread = None
        component.fastapi_host = "127.0.0.1"
        component.fastapi_port = 8000
        component.fastapi_https_port = 8443
        component.ssl_keyfile = ""
        component.ssl_certfile = ""
        component.ssl_keyfile_password = ""
        component.log_identifier = "[test]"
        component.database_url = None
        component.platform_database_url = None
        component.get_config = MagicMock(return_value={})
        return component

    def test_configured_prefix_is_passed_as_root_path(self):
        component = self._component()
        component.fastapi_root_path = "/agent-mesh"

        mock_config = self._start_server(component)

        assert mock_config.call_args.kwargs["root_path"] == "/agent-mesh"

    def test_default_is_an_empty_prefix(self):
        component = self._component()
        component.fastapi_root_path = ""

        mock_config = self._start_server(component)

        assert mock_config.call_args.kwargs["root_path"] == ""
