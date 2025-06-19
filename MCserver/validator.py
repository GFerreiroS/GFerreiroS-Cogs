import re


def validate_properties(file_bytes: bytes) -> tuple[bool, str]:
    """
    Validate a server.properties file's content:
    - Must be UTF-8 text
    - Only blank lines, comments (#), or key=value pairs with safe keys
    - Reject if any line contains suspicious characters or invalid format

    Returns (True, "") if valid, otherwise (False, reason).
    """
    # Decode to text
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return False, "File is not valid UTF-8 text"

    # Regex for key=value lines: key may contain letters, numbers, dots, underscores, hyphens
    key_regex = re.compile(r"^[A-Za-z0-9._-]+=[^\n]*$")

    suspicious_patterns = ["`", ";", ">", "<", "$(", "|"]

    # Check each line
    for idx, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        # Allow blank lines and comments
        if not line or line.startswith("#"):
            continue
        # Validate key=value format
        if not key_regex.match(line):
            return False, f"Invalid format on line {idx}: '{raw_line}'"
        # Check for suspicious characters
        for pat in suspicious_patterns:
            if pat in line:
                return False, f"Suspicious character '{pat}' on line {idx}"

    return True, ""
