import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render(text: str, variables: dict[str, Any]) -> str:
    """
    Substitute {{variable_name}} placeholders with values from `variables`.
    A placeholder with no matching key is left unsubstituted rather than
    blanked out, so a template-authoring bug stays visible in the output.
    """

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            return match.group(0)
        return str(variables[key])

    return _PLACEHOLDER_RE.sub(_replace, text)
