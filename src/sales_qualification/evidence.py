"""Observe actual HTTP responses before SDK usage defaults or tool dispatch."""
import json
from langchain_core.callbacks import BaseCallbackHandler


class ProviderProtocolError(RuntimeError):
    pass


def response_guard(observation):
    def observe(response):
        response.read()
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        event = {"endpoint": {"scheme": response.request.url.scheme, "host": response.request.url.host, "port": response.request.url.port},
                 "http_status": response.status_code, "request_id": response.headers.get("x-request-id"),
                 "response_id": body.get("id"), "model": body.get("model"), "status": body.get("status"),
                 "reported_usage": body.get("usage"), "output": body.get("output"), "protocol_error": None}
        observation["responses"].append(event)
        if response.status_code != 200:
            return  # Preserve ordinary SDK HTTP error handling; retries are disabled.
        problem = None
        output = body.get("output")
        if body.get("status") != "completed" or body.get("error") or body.get("incomplete_details"):
            problem = "response_not_completed"
        elif not isinstance(output, list) or not output:
            problem = "missing_output"
        else:
            calls = [item for item in output if isinstance(item, dict) and item.get("type") == "function_call"]
            if len(calls) > 1:
                problem = "parallel_tool_calls_not_supported"
            for item in output:
                if not isinstance(item, dict):
                    problem = "invalid_output_item"
                    break
                if item.get("type") == "message":
                    if item.get("status") != "completed":
                        problem = "message_not_completed"
                    if any(isinstance(part, dict) and part.get("type") == "refusal" for part in item.get("content", [])):
                        problem = "refusal"
                if item.get("type") == "function_call" and item.get("status") not in (None, "completed"):
                    problem = "function_call_not_completed"
        event["protocol_error"] = problem
        if problem:
            raise ProviderProtocolError(problem)
    return observe


class Trace(BaseCallbackHandler):
    def __init__(self, observation):
        self.observation = observation
        self.tools = {}

    def on_llm_end(self, response, **kwargs):
        for batch in response.generations:
            for generation in batch:
                message = getattr(generation, "message", None)
                if message is not None:
                    self.observation["model_messages"].append(message.model_dump(mode="json"))

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        try:
            arguments = json.loads(input_str)
        except ValueError:
            arguments = input_str
        event = {"name": serialized.get("name"), "input": arguments, "output": None, "error_type": None}
        self.tools[run_id] = event
        self.observation["tool_calls"].append(event)

    def on_tool_end(self, output, *, run_id, **kwargs):
        if run_id in self.tools:
            self.tools[run_id]["output"] = output.model_dump(mode="json") if hasattr(output, "model_dump") else output

    def on_tool_error(self, error, *, run_id, **kwargs):
        if run_id in self.tools:
            self.tools[run_id]["error_type"] = type(error).__name__


def measured_usage(observation):
    responses = observation["responses"]
    keys = ("input_tokens", "output_tokens", "total_tokens")
    complete = bool(responses) and all(isinstance(event["reported_usage"], dict) and
        all(type(event["reported_usage"].get(key)) is int and event["reported_usage"][key] >= 0 for key in keys)
        for event in responses)
    observation["usage_complete"] = complete
    if not complete:
        return None
    return {"requests": len(responses), **{key: sum(event["reported_usage"][key] for event in responses) for key in keys}}
