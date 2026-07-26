"""Shared argparse extensions for btrfs-style unique-prefix matching."""

import argparse


class PrefixMatchError(ValueError):
    """Base error for failed unique-prefix resolution."""


class NoPrefixMatch(PrefixMatchError):
    """Raised when a token does not prefix any available choice."""


class AmbiguousPrefix(PrefixMatchError):
    """Raised when a token prefixes more than one available choice."""


def resolve_unique_prefix(value, choices, *, label="value", case_sensitive=True):
    """Return the canonical choice selected by an exact or unique prefix.

    Exact matches always win, even if the exact choice is also a prefix of a
    longer choice.  Prefixes that match zero or multiple choices are rejected.
    """
    choices = tuple(choices)
    normalize = (lambda item: item) if case_sensitive else str.casefold
    token = normalize(value)

    for choice in choices:
        if normalize(choice) == token:
            return choice

    matches = sorted(
        choice for choice in choices if normalize(choice).startswith(token)
    )
    if len(matches) == 1:
        return matches[0]
    if not matches:
        available = ", ".join(choices)
        raise NoPrefixMatch(
            f"invalid {label} {value!r}; expected one of: {available}"
        )

    available = ", ".join(matches)
    raise AmbiguousPrefix(f"ambiguous {label} {value!r}: {available}")


def prefix_choice(*choices, label="value", case_sensitive=True):
    """Build an argparse ``type`` converter using unique-prefix matching."""
    if not choices:
        raise ValueError("prefix_choice requires at least one choice")

    def parse(value):
        try:
            return resolve_unique_prefix(
                value,
                choices,
                label=label,
                case_sensitive=case_sensitive,
            )
        except PrefixMatchError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from None

    return parse


class UniquePrefixSubparsersAction(argparse._SubParsersAction):
    """Resolve subcommands by exact name or an unambiguous prefix."""

    def __call__(self, parser, namespace, values, option_string=None):
        command = values[0]
        if command not in self._name_parser_map:
            try:
                values[0] = resolve_unique_prefix(
                    command,
                    self._name_parser_map,
                    label="command",
                )
            except NoPrefixMatch:
                # Let argparse produce its standard invalid-choice message.
                pass
            except AmbiguousPrefix as exc:
                raise argparse.ArgumentError(self, str(exc)) from None

        return super().__call__(parser, namespace, values, option_string)


class UniquePrefixArgumentParser(argparse.ArgumentParser):
    """ArgumentParser whose subcommands accept unambiguous prefixes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.register("action", "parsers", UniquePrefixSubparsersAction)

    def _check_value(self, action, value):
        # Recent argparse versions validate subparser ``choices`` before the
        # action's __call__ method gets a chance to canonicalize the token.
        if isinstance(action, UniquePrefixSubparsersAction):
            if value in action._name_parser_map:
                return
            try:
                resolve_unique_prefix(
                    value,
                    action._name_parser_map,
                    label="command",
                )
                return
            except NoPrefixMatch:
                pass
            except AmbiguousPrefix as exc:
                raise argparse.ArgumentError(action, str(exc)) from None

        return super()._check_value(action, value)
