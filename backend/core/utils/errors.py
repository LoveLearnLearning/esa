"""Shared runtime error types."""


class ModelContextOverflow(ValueError):
    """The rendered prompt cannot fit the model's physical context window."""
