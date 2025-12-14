import hashlib
from typing import Union


def compute_content_hash(data: Union[str, bytes]) -> str:
    if isinstance(data, str):
        content = data.encode("utf-8")
    else:
        content = data

    return hashlib.sha256(content).hexdigest()[:32]
