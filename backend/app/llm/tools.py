"""
LLM tool and schema definitions.

We chose response_format=json_schema (not function-calling / tool_choice) for
adverse-media structuring because it is simpler: one response_format parameter,
no tool list to maintain, and identical structured-output guarantees on any
model that supports the json_schema response format.

If a future integration requires tool_choice (e.g. parallel tool calls for
multi-step entity resolution), add the tool definitions here and keep them
synchronised with the Pydantic models in app/models.py.
"""
