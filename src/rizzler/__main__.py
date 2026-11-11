"""Start with: python -m rizzler"""
from __future__ import annotations
import os
import uvicorn


def main():
    uvicorn.run('rizzler.api:create_app', host=os.getenv('RIZZLER_HOST', '127.0.0.1'),
                port=int(os.getenv('RIZZLER_PORT', '8000')), factory=True,
                log_level='info')


if __name__ == '__main__':
    main()
