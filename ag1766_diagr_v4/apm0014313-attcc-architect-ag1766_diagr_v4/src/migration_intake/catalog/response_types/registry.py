"""
Response type registry.

Central registry for all 25 response types. Each type is registered
once and looked up by code when processing catalog definitions,
form submissions, and workbook imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from migration_intake.catalog.response_types.base import ResponseType


class ResponseTypeRegistry:
    """
    Central registry for response types.

    Usage:
        registry = ResponseTypeRegistry()
        registry.register(BooleanType())
        registry.register(TextType())

        bool_type = registry.get("BOOLEAN")
        if bool_type:
            result = bool_type.parse_form(form_data)
    """

    def __init__(self) -> None:
        self._types: dict[str, ResponseType] = {}

    def register(self, response_type: ResponseType) -> None:
        """
        Register a response type.

        Args:
            response_type: The response type instance to register

        Raises:
            ValueError: If a type with the same code is already registered
        """
        code = response_type.code
        if code in self._types:
            raise ValueError(
                f"Response type '{code}' is already registered. "
                "Duplicate registration is not allowed."
            )
        self._types[code] = response_type

    def get(self, code: str) -> ResponseType | None:
        """
        Get a response type by code.

        Args:
            code: The response type code (e.g., 'BOOLEAN', 'TEXT')

        Returns:
            The response type instance, or None if not found
        """
        return self._types.get(code)

    def get_required(self, code: str) -> ResponseType:
        """
        Get a response type by code, raising if not found.

        Args:
            code: The response type code

        Returns:
            The response type instance

        Raises:
            KeyError: If the type is not registered
        """
        response_type = self._types.get(code)
        if response_type is None:
            raise KeyError(f"Response type '{code}' is not registered")
        return response_type

    def list_codes(self) -> list[str]:
        """
        List all registered type codes.

        Returns:
            List of registered type codes in alphabetical order
        """
        return sorted(self._types.keys())

    def count(self) -> int:
        """
        Get the number of registered types.

        Returns:
            Count of registered types
        """
        return len(self._types)

    def is_registered(self, code: str) -> bool:
        """
        Check if a type code is registered.

        Args:
            code: The response type code

        Returns:
            True if registered, False otherwise
        """
        return code in self._types

    def all_types(self) -> list[ResponseType]:
        """
        Get all registered response types.

        Returns:
            List of all registered response type instances
        """
        return list(self._types.values())

    def computed_types(self) -> list[ResponseType]:
        """
        Get all computed (non-editable) response types.

        Returns:
            List of computed response type instances
        """
        return [t for t in self._types.values() if t.is_computed]

    def editable_types(self) -> list[ResponseType]:
        """
        Get all editable (non-computed) response types.

        Returns:
            List of editable response type instances
        """
        return [t for t in self._types.values() if not t.is_computed]


# Global registry instance
_global_registry: ResponseTypeRegistry | None = None


def get_global_registry() -> ResponseTypeRegistry:
    """
    Get the global response type registry.

    Creates the registry on first access. Use this for production code.
    Tests should create their own registry instances.

    Returns:
        The global registry instance
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ResponseTypeRegistry()
    return _global_registry


def reset_global_registry() -> None:
    """
    Reset the global registry.

    Only use this in tests to ensure clean state.
    """
    global _global_registry
    _global_registry = None
