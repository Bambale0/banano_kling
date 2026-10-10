"""Isolated PDF metadata worker: no application imports and no network access."""
from __future__ import annotations

import sys


def main() -> None:
    import resource

    # Parsing is outside the webhook process and bounded against hostile files.
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024**2, 768 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    from pypdf import PdfReader

    reader = PdfReader(sys.argv[1], strict=False)
    if reader.is_encrypted:
        raise ValueError('Encrypted PDF is not supported')
    print(len(reader.pages))


if __name__ == '__main__':
    main()
