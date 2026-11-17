"""Scalable command line: `python -m scalable` fetches every feed and writes web/data/feeds.json."""
from . import feeds

if __name__ == "__main__":
    feeds.run()
