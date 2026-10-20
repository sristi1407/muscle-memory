"""The action tool schema the discovery agent exposes to the model.

It mirrors the ``Action`` model 1:1 — one ``act()`` call per turn. Tool-calling
(not free text) is what gives us clean, recordable steps to compile.
"""

ACT_TOOL = {
    "type": "function",
    "function": {
        "name": "act",
        "description": "Perform exactly ONE UI action on the current screen to progress toward the goal.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["navigate", "click", "type", "select", "read", "finish"],
                    "description": "The kind of action. Use 'finish' when the goal is complete.",
                },
                "target": {
                    "type": "string",
                    "description": "Accessible name of the element (e.g. 'Member ID', 'Search'). Omit for navigate/finish.",
                },
                "text": {"type": "string", "description": "Text to type (action=type) or option to pick (action=select)."},
                "url": {"type": "string", "description": "URL to open (action=navigate)."},
                "output_key": {
                    "type": "string",
                    "description": "For action=read: the output name to store the value under (e.g. 'savings_balance').",
                },
                "reason": {"type": "string", "description": "One short clause: why this action now."},
            },
            "required": ["action"],
        },
    },
}
