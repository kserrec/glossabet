"""Support ``python -m glossabet`` in installed and source environments."""

from glossabet.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
