from typing import Any


def get_completion_text(completion: Any) -> str:
    if not (choice := completion.choices[0] if completion.choices else None):
        return ""

    message = getattr(choice, "message", None)
    content = getattr(message, "content", "")

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        chunks = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
                continue

            part_type = getattr(part, "type", None)
            part_text = getattr(part, "text", None)
            if part_type == "text" and isinstance(part_text, str):
                chunks.append(part_text)

        return "".join(chunks).strip()

    return str(content).strip()
