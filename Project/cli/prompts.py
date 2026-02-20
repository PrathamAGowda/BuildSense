"""
Reusable CLI prompt helpers — validated input, no crashes.
"""

from typing import List, Optional


def prompt_float(
    prompt:     str,
    min_val:    float = 0.0,
    max_val:    Optional[float] = None,
    allow_zero: bool  = False,
) -> float:
    """Prompt for a float, re-asking on bad input."""
    while True:
        raw = input(prompt).strip()
        try:
            value = float(raw)
        except ValueError:
            print("  ⚠  Please enter a valid number.")
            continue
        if not allow_zero and value <= min_val:
            print(f"  ⚠  Value must be greater than {min_val}.")
            continue
        if allow_zero and value < min_val:
            print(f"  ⚠  Value must be at least {min_val}.")
            continue
        if max_val is not None and value > max_val:
            print(f"  ⚠  Value must be at most {max_val}.")
            continue
        return value


def prompt_int(prompt: str, min_val: int = 1, max_val: Optional[int] = None) -> int:
    """Prompt for an integer within an optional range."""
    while True:
        raw = input(prompt).strip()
        try:
            value = int(raw)
        except ValueError:
            print("  ⚠  Please enter a whole number.")
            continue
        if value < min_val:
            print(f"  ⚠  Value must be at least {min_val}.")
            continue
        if max_val is not None and value > max_val:
            print(f"  ⚠  Value must be at most {max_val}.")
            continue
        return value


def prompt_str(prompt: str, allow_empty: bool = False) -> str:
    """Prompt for a non-empty string."""
    while True:
        value = input(prompt).strip()
        if not value and not allow_empty:
            print("  ⚠  Input cannot be empty.")
            continue
        return value


def prompt_confirm(prompt: str, default: bool = True) -> bool:
    """Yes/No confirmation. Returns True for yes."""
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        raw = input(f"{prompt} {hint}: ").strip().lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        if raw == "":
            return default
        print("  ⚠  Please enter y or n.")


def prompt_choice(prompt: str, options: List[str]) -> int:
    """Display a numbered list and return the chosen 0-based index."""
    for i, opt in enumerate(options, 1):
        print(f"    {i}. {opt}")
    while True:
        raw = input(prompt).strip()
        try:
            idx = int(raw) - 1
        except ValueError:
            print("  ⚠  Please enter a number.")
            continue
        if 0 <= idx < len(options):
            return idx
        print(f"  ⚠  Please enter 1–{len(options)}.")
