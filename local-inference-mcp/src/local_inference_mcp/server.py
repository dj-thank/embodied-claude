"""Typed MCP server exposing bounded loopback local inference."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer

from .config import InferenceConfig
from .inference import LocalInference, UrllibJsonTransport

InferenceFactory = Callable[[], LocalInference]


def _default_inference() -> LocalInference:
    return LocalInference(InferenceConfig.from_env(), UrllibJsonTransport())


def create_server(inference_factory: InferenceFactory = _default_inference) -> MCPServer:
    """Create the server with an injectable inference adapter."""
    server = MCPServer("local-inference-mcp")

    @server.tool(
        name="get_local_inference_status",
        description=(
            "Check the configured loopback-only local LLM endpoint and list its models. "
            "This does not start a server, load a model, or access a non-loopback network."
        ),
    )
    def get_local_inference_status() -> dict[str, Any]:
        return inference_factory().status()

    @server.tool(
        name="ask_local_model",
        description=(
            "Ask a loopback-only local LLM to perform bounded local text inference. "
            "The model cannot call Sanpoloid tools through this helper."
        ),
    )
    def ask_local_model(
        prompt: str,
        system_prompt: str = "",
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> dict[str, Any]:
        result = inference_factory().complete(
            prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return result.as_dict()

    return server


mcp = create_server()


def main() -> None:
    """Run the local inference server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
