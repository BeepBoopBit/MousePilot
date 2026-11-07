"""Text entry deliberately excludes Enter, Tab, and other control characters."""


def utf16_units(text):
    if not isinstance(text, str) or not 1 <= len(text) <= 2000:
        raise ValueError("Text must contain 1 to 2000 characters")
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 or char in "\u2028\u2029" for char in text):
        raise ValueError("Control characters and line breaks are not allowed")
    encoded = text.encode("utf-16-le")
    return [int.from_bytes(encoded[i : i + 2], "little") for i in range(0, len(encoded), 2)]
