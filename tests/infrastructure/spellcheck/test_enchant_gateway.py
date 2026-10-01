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

"""Characterize the optional Enchant boundary without touching personal dictionaries."""

from __future__ import annotations

from collections.abc import Callable
import sys
from types import ModuleType

import pytest

from substitute.infrastructure.spellcheck.enchant_gateway import (
    EnchantSpellCheckGateway,
)


class _Dictionary:
    """Record external dictionary operations and inject provider responses or failures."""

    def __init__(self) -> None:
        """Start with rejected words and deterministic provider suggestions."""
        self.check_result: object = False
        self.suggestions: list[object] = ["first", 42, "third", "fourth"]
        self.calls: list[tuple[str, str]] = []
        self.failing_operation: str | None = None
        self.failure = RuntimeError("dictionary operation failed")

    def _record(self, operation: str, word: str) -> None:
        """Record provider input and optionally propagate the configured failure."""
        self.calls.append((operation, word))
        if operation == self.failing_operation:
            raise self.failure

    def check(self, word: str) -> object:
        """Expose provider truthiness for the gateway's boolean conversion."""
        self._record("check", word)
        return self.check_result

    def suggest(self, word: str) -> list[object]:
        """Expose provider values for the gateway's string conversion and limit."""
        self._record("suggest", word)
        return self.suggestions

    def add_to_session(self, word: str) -> None:
        """Record a session-only addition without writing user data."""
        self._record("ignore", word)

    def add(self, word: str) -> None:
        """Record a persistent-add request without writing user data."""
        self._record("add", word)


class _Broker:
    """Represent the optional provider's broker boundary with controlled failures."""

    def __init__(self) -> None:
        """Initialize an available fake dictionary and empty external requests."""
        self.dictionary = _Dictionary()
        self.available = True
        self.ordering_error: Exception | None = None
        self.request_error: Exception | None = None
        self.orderings: list[tuple[str, str]] = []
        self.language_queries: list[str] = []
        self.dictionary_requests: list[str] = []

    def set_ordering(self, tag: str, ordering: str) -> None:
        """Record provider precedence and optionally reject that advisory setting."""
        self.orderings.append((tag, ordering))
        if self.ordering_error is not None:
            raise self.ordering_error

    def dict_exists(self, tag: str) -> bool:
        """Return controlled availability for the requested language."""
        self.language_queries.append(tag)
        return self.available

    def request_dict(self, tag: str) -> object:
        """Return the external dictionary or its original initialization failure."""
        self.dictionary_requests.append(tag)
        if self.request_error is not None:
            raise self.request_error
        return self.dictionary


class _Enchant(ModuleType):
    """Offer an importable optional module backed entirely by typed fakes."""

    def __init__(self, broker: object, error: Exception | None = None) -> None:
        """Store the external broker or a broker-construction failure."""
        super().__init__("enchant")
        self.broker = broker
        self.error = error

    def Broker(self) -> object:
        """Construct the controlled broker while preserving provider exceptions."""
        if self.error is not None:
            raise self.error
        return self.broker


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> _Broker:
    """Replace the optional package per test and restore module state afterward."""
    broker = _Broker()
    monkeypatch.setitem(sys.modules, "enchant", _Enchant(broker))
    return broker


def _assert_unavailable(gateway: EnchantSpellCheckGateway, reason: str) -> None:
    """Prove unavailable providers remain harmless and cannot write dictionaries."""
    assert gateway.is_available() is False
    assert gateway.availability_reason() == reason
    assert gateway.check_word("typo") is True
    assert gateway.suggest("typo") == ()
    assert gateway.supports_session_ignore() is False
    gateway.ignore_for_session("typo")
    assert gateway.supports_persistent_add() is False
    assert gateway.add_to_dictionary("typo") is False


def test_missing_enchant_package_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep an absent optional package from breaking prompt spellcheck consumers."""
    monkeypatch.setitem(sys.modules, "enchant", None)
    _assert_unavailable(
        EnchantSpellCheckGateway(language_tag="en_US"), "PyEnchant is not installed."
    )


def test_missing_dictionary_reports_language_without_requesting_it(
    broker: _Broker,
) -> None:
    """Report the absent language rather than constructing an unsupported dictionary."""
    broker.available = False
    _assert_unavailable(
        EnchantSpellCheckGateway(language_tag="xx_XX"),
        "No Enchant dictionary is installed for xx_XX.",
    )
    assert broker.language_queries == ["xx_XX"]
    assert broker.dictionary_requests == []


@pytest.mark.parametrize("stage", ["broker", "dictionary"])
def test_provider_initialization_failure_preserves_reason(
    monkeypatch: pytest.MonkeyPatch, broker: _Broker, stage: str
) -> None:
    """Retain the provider's diagnostic exception at either initialization boundary."""
    failure = RuntimeError("provider unavailable")
    if stage == "broker":
        monkeypatch.setitem(sys.modules, "enchant", _Enchant(broker, failure))
    else:
        broker.request_error = failure
    _assert_unavailable(
        EnchantSpellCheckGateway(language_tag="en_US"),
        "Enchant initialization failed: RuntimeError('provider unavailable').",
    )


@pytest.mark.parametrize("ordering_error", [None, RuntimeError("ordering unavailable")])
def test_provider_ordering_is_advisory_and_language_is_forwarded(
    broker: _Broker, ordering_error: Exception | None
) -> None:
    """Keep a usable dictionary even if the provider rejects preferred ordering."""
    broker.ordering_error = ordering_error
    gateway = EnchantSpellCheckGateway(language_tag="fr_FR")
    assert gateway.is_available() is True
    assert gateway.availability_reason() is None
    assert broker.orderings == [("*", "nuspell,hunspell,aspell")]
    assert broker.language_queries == ["fr_FR"]
    assert broker.dictionary_requests == ["fr_FR"]


@pytest.mark.parametrize(
    ("response", "expected"), [(False, False), (0, False), (1, True)]
)
def test_check_word_preserves_boolean_conversion(
    broker: _Broker, response: object, expected: bool
) -> None:
    """Normalize the external provider's result to a real bool without rewriting input."""
    broker.dictionary.check_result = response
    gateway = EnchantSpellCheckGateway(language_tag="en_US")
    assert gateway.check_word("MixedCase") is expected
    assert broker.dictionary.calls == [("check", "MixedCase")]


@pytest.mark.parametrize(
    ("limit", "expected"),
    [
        (None, ("first", "42", "third", "fourth")),
        (2, ("first", "42")),
        (0, ()),
        (-1, ("first", "42", "third")),
    ],
)
def test_suggestions_preserve_order_conversion_and_slicing(
    broker: _Broker, limit: int | None, expected: tuple[str, ...]
) -> None:
    """Retain provider order, stringify values, and preserve zero and negative limits."""
    gateway = EnchantSpellCheckGateway(language_tag="en_US")
    actual = (
        gateway.suggest("typo")
        if limit is None
        else gateway.suggest("typo", limit=limit)
    )
    assert actual == expected
    assert broker.dictionary.calls == [("suggest", "typo")]


def test_default_suggestions_stop_at_eight(broker: _Broker) -> None:
    """Apply the public default limit when the provider offers additional corrections."""
    broker.dictionary.suggestions = list(range(10))
    gateway = EnchantSpellCheckGateway(language_tag="en_US")
    assert gateway.suggest("typo") == ("0", "1", "2", "3", "4", "5", "6", "7")


def test_dictionary_actions_forward_word_and_preserve_success(broker: _Broker) -> None:
    """Separate session ignore from persistent add and report the provider's success."""
    gateway = EnchantSpellCheckGateway(language_tag="en_US")
    assert gateway.supports_session_ignore() is True
    assert gateway.supports_persistent_add() is True
    gateway.ignore_for_session("SessionWord")
    assert gateway.add_to_dictionary("StoredWord") is True
    assert broker.dictionary.calls == [("ignore", "SessionWord"), ("add", "StoredWord")]


@pytest.mark.parametrize(
    ("operation", "action"),
    [
        ("check", lambda gateway: gateway.check_word("typo")),
        ("suggest", lambda gateway: gateway.suggest("typo")),
        ("ignore", lambda gateway: gateway.ignore_for_session("typo")),
        ("add", lambda gateway: gateway.add_to_dictionary("typo")),
    ],
)
def test_dictionary_operation_failure_is_not_reported_as_success(
    broker: _Broker,
    operation: str,
    action: Callable[[EnchantSpellCheckGateway], object],
) -> None:
    """Leave operation errors available to the service's existing recovery boundary."""
    broker.dictionary.failing_operation = operation
    gateway = EnchantSpellCheckGateway(language_tag="en_US")
    with pytest.raises(RuntimeError) as caught:
        action(gateway)
    assert caught.value is broker.dictionary.failure
    assert broker.dictionary.calls == [(operation, "typo")]


@pytest.mark.parametrize("noncallable", [False, True])
def test_malformed_module_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, noncallable: bool
) -> None:
    """Validate optional module construction before exposing a usable gateway."""
    module = ModuleType("enchant")
    if noncallable:
        monkeypatch.setattr(module, "Broker", 0, raising=False)
    monkeypatch.setitem(sys.modules, "enchant", module)
    _assert_unavailable(
        EnchantSpellCheckGateway(language_tag="en_US"),
        "Enchant initialization failed: "
        "TypeError('PyEnchant module does not expose a callable Broker.').",
    )


@pytest.mark.parametrize("member", [None, "dict_exists", "request_dict"])
def test_malformed_broker_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, broker: _Broker, member: str | None
) -> None:
    """Validate required dictionary discovery methods before calling them."""
    if member is None:
        monkeypatch.setitem(sys.modules, "enchant", _Enchant(object()))
    else:
        monkeypatch.setattr(broker, member, 0)
    _assert_unavailable(
        EnchantSpellCheckGateway(language_tag="en_US"),
        "Enchant initialization failed: "
        "TypeError('Enchant broker does not expose the required dictionary methods.').",
    )


@pytest.mark.parametrize("member", [None, "check", "suggest", "add_to_session", "add"])
def test_malformed_dictionary_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, broker: _Broker, member: str | None
) -> None:
    """Require callable word operations before reporting provider availability."""
    if member is None:

        def malformed_dictionary(tag: str) -> object:
            """Return a provider object without dictionary methods."""
            return object()

        monkeypatch.setattr(broker, "request_dict", malformed_dictionary)
    else:
        monkeypatch.setattr(broker.dictionary, member, 0)
    _assert_unavailable(
        EnchantSpellCheckGateway(language_tag="en_US"),
        "Enchant initialization failed: "
        "TypeError('Enchant dictionary does not expose the required word methods.').",
    )


def test_noncallable_advisory_ordering_keeps_dictionary_available(
    monkeypatch: pytest.MonkeyPatch, broker: _Broker
) -> None:
    """Preserve tolerant ordering failure even when an external ordering API is invalid."""
    monkeypatch.setattr(broker, "set_ordering", 0)
    gateway = EnchantSpellCheckGateway(language_tag="en_US")
    assert gateway.is_available() is True
    assert gateway.availability_reason() is None
    assert broker.dictionary_requests == ["en_US"]


class _UnorderedBroker:
    """Represent a provider with dictionary support but no advisory ordering API."""

    def __init__(self, broker: _Broker) -> None:
        """Retain the controlled external dictionary operations."""
        self.broker = broker

    def dict_exists(self, tag: str) -> bool:
        """Forward language availability to the controlled provider."""
        return self.broker.dict_exists(tag)

    def request_dict(self, tag: str) -> object:
        """Forward dictionary construction without adding an ordering API."""
        return self.broker.request_dict(tag)


def test_missing_advisory_ordering_keeps_dictionary_available(
    monkeypatch: pytest.MonkeyPatch, broker: _Broker
) -> None:
    """Keep optional provider-ordering absence equivalent to a rejected preference."""
    monkeypatch.setitem(sys.modules, "enchant", _Enchant(_UnorderedBroker(broker)))
    gateway = EnchantSpellCheckGateway(language_tag="en_US")
    assert gateway.is_available() is True
    assert gateway.availability_reason() is None
    assert broker.dictionary_requests == ["en_US"]
