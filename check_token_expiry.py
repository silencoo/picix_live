"""Compatibility wrapper for the relocated token diagnostic."""
from scripts.diagnostics.check_token import main


if __name__ == "__main__":
    raise SystemExit(main())
