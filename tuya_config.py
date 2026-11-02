"""Small .env parser shared by the wizard and MCP server.

Supports optional 'export', quoted values, and unquoted trailing comments.
Quotes are not evaluated or unescaped; credentials are kept verbatim.
"""


def read_env(path):
    values = {}
    with open(path, encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip().removeprefix("export ").strip()
            value = value.strip()
            if value.startswith(("'", '"')):
                quote = value[0]
                closing = value.find(quote, 1)
                if closing > 0 and (
                    not value[closing + 1:].strip()
                    or value[closing + 1:].lstrip().startswith("#")
                ):
                    value = value[1:closing]
            else:
                # A literal '#' without a preceding space may belong to the key.
                value = value.split(" #", 1)[0].strip()
            if name:
                values[name] = value
    return values
