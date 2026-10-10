"""Isolated document metadata worker with hard memory and CPU ceilings."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024**2, 384 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    path = Path(sys.argv[1])
    if path.suffix.lower() == '.pdf':
        from pypdf import PdfReader

        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            raise ValueError('Encrypted PDF is not supported')
        print(len(reader.pages))
        return
    import zipfile

    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(entry.file_size for entry in entries) > 250 * 1024**2:
            raise ValueError('Document archive expands beyond the safe limit')
        if any(entry.flag_bits & 1 for entry in entries):
            raise ValueError('Encrypted documents are not supported')
        if path.suffix.lower() == '.pptx':
            pages = sum(bool(re.fullmatch(r'ppt/slides/slide\d+\.xml', entry.filename)) for entry in entries)
            if pages <= 0:
                raise ValueError('Presentation has no slides')
            print(pages)
        else:
            # Word/Keynote page count depends on rendering, not ZIP entries.
            print('unknown')


if __name__ == '__main__':
    main()
