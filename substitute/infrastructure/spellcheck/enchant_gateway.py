#    SugarSubstitute - The desktop native Qt front-end for ComfyUI
#    Copyright (C) 2026  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Adapt PyEnchant dictionaries to the prompt spellcheck gateway contract."""

from __future__ import annotations

import importlib
import sys
from typing import Protocol, runtime_checkable

from substitute.shared.logging.logger import get_logger, log_warning

_LOGGER = get_logger("infrastructure.spellcheck.enchant")


@runtime_checkable
class _EnchantDictionary(Protocol):
    """Describe the PyEnchant word operations consumed by this adapter."""

    def check(self, word: str) -> bool:
        """Report whether the dictionary accepts a word."""

    def suggest(self, word: str) -> list[str]:
        """Return provider-ordered corrections for a word."""

    def add_to_session(self, word: str) -> None:
        """Accept a word in the current dictionary session."""

    def add(self, word: str) -> None:
        """Persist a word in the provider's personal dictionary."""


@runtime_checkable
class _EnchantBroker(Protocol):
    """Describe dictionary discovery before validating the returned provider."""

    def dict_exists(self, tag: str) -> bool:
        """Report whether a language dictionary is installed."""

    def request_dict(self, tag: str) -> object:
        """Return an external dictionary whose callable surface needs validation."""


@runtime_checkable
class _EnchantProviderOrdering(Protocol):
    """Describe advisory ordering independently of required dictionary operations."""

    def set_ordering(self, tag: str, ordering: str) -> None:
        """Set provider precedence for the requested language pattern."""


@runtime_checkable
class _EnchantModule(Protocol):
    """Describe the lazy optional import before validating its broker."""

    def Broker(self) -> object:
        """Construct an external broker whose callable surface needs validation."""


class EnchantSpellCheckGateway:
    """Use Enchant providers such as Hunspell or Nuspell for spellcheck."""

    def __init__(self, *, language_tag: str) -> None:
        """Load the requested Enchant dictionary when available."""

        self._language_tag = language_tag
        self._dictionary: _EnchantDictionary | None = None
        self._reason: str | None = None
        try:
            enchant = importlib.import_module("enchant")
            if not isinstance(enchant, _EnchantModule) or not callable(enchant.Broker):
                raise TypeError("PyEnchant module does not expose a callable Broker.")
            broker = enchant.Broker()
            if not isinstance(broker, _EnchantBroker) or not all(
                callable(method) for method in (broker.dict_exists, broker.request_dict)
            ):
                raise TypeError(
                    "Enchant broker does not expose the required dictionary methods."
                )
            try:
                if not isinstance(broker, _EnchantProviderOrdering) or not callable(
                    broker.set_ordering
                ):
                    raise TypeError("Enchant provider ordering is unavailable.")
                broker.set_ordering("*", "nuspell,hunspell,aspell")
            except Exception:
                log_warning(
                    _LOGGER,
                    "Enchant provider ordering could not be set",
                    platform=sys.platform,
                    language_tag=language_tag,
                )
            if not broker.dict_exists(language_tag):
                self._reason = f"No Enchant dictionary is installed for {language_tag}."
                return
            dictionary = broker.request_dict(language_tag)
            if not isinstance(dictionary, _EnchantDictionary) or not all(
                callable(method)
                for method in (
                    dictionary.check,
                    dictionary.suggest,
                    dictionary.add_to_session,
                    dictionary.add,
                )
            ):
                raise TypeError(
                    "Enchant dictionary does not expose the required word methods."
                )
            self._dictionary = dictionary
        except ImportError:
            self._reason = "PyEnchant is not installed."
        except Exception as error:
            self._reason = f"Enchant initialization failed: {error!r}."

    def is_available(self) -> bool:
        """Return whether an Enchant dictionary loaded successfully."""

        return self._dictionary is not None

    def availability_reason(self) -> str | None:
        """Return the Enchant unavailability reason."""

        return self._reason

    def check_word(self, word: str) -> bool:
        """Return whether Enchant accepts one word."""

        if self._dictionary is None:
            return True
        return bool(self._dictionary.check(word))

    def suggest(self, word: str, *, limit: int = 8) -> tuple[str, ...]:
        """Return Enchant suggestions for one rejected word."""

        if self._dictionary is None:
            return ()
        return tuple(str(suggestion) for suggestion in self._dictionary.suggest(word))[
            :limit
        ]

    def supports_session_ignore(self) -> bool:
        """Return whether the loaded dictionary supports session words."""

        return self._dictionary is not None

    def ignore_for_session(self, word: str) -> None:
        """Accept one word for the lifetime of the Enchant dictionary object."""

        if self._dictionary is not None:
            self._dictionary.add_to_session(word)

    def supports_persistent_add(self) -> bool:
        """Return whether the loaded dictionary supports personal word lists."""

        return self._dictionary is not None

    def add_to_dictionary(self, word: str) -> bool:
        """Add one word to the Enchant personal dictionary."""

        if self._dictionary is None:
            return False
        self._dictionary.add(word)
        return True


__all__ = ["EnchantSpellCheckGateway"]
