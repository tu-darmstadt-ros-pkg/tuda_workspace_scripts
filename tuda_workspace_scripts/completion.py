import argparse
from typing import List
from argcomplete.completers import ChoicesCompleter

try:
    from argcomplete.completers import SuppressCompleter
except ImportError:
    SuppressCompleter = object
from argcomplete import CompletionFinder


class PrefixFilteredChoicesCompleter(ChoicesCompleter):
    def __init__(self, choices, *args, **kwargs):
        super(PrefixFilteredChoicesCompleter, self).__init__(choices, *args, **kwargs)

    def __call__(self, **kwargs):
        options = super(PrefixFilteredChoicesCompleter, self).__call__(**kwargs)
        prefix = kwargs.get("prefix", "")
        return [option for option in options if option.startswith(prefix)]


class SuppressIfPackagesProvidedCompleter(SuppressCompleter):
    def suppress(self, parsed_args, **kwargs):
        return getattr(parsed_args, "packages", None) is not None


class SmartCompletionFinder(CompletionFinder):
    def __init__(self, *args, **kwargs):
        super(SmartCompletionFinder, self).__init__(*args, **kwargs)

    def _get_completions(
        self, comp_words, cword_prefix, cword_prequote, last_wordbreak_pos
    ):
        current_cword = comp_words[-1]
        for action in self._parser._actions:
            if not current_cword in action.option_strings:
                continue
            try:
                if action.completer:
                    completions = action.completer(
                        prefix=cword_prefix,
                        action=action,
                        parser=self._parser,
                        parsed_args=argparse.Namespace(),
                    )
                    completions = self.filter_completions(completions)
                    completions = self.quote_completions(
                        completions, cword_prequote, last_wordbreak_pos
                    )
                    return completions
            except AttributeError:
                pass
            if action.choices:
                completions = [
                    choice
                    for choice in action.choices
                    if cword_prefix is None or choice.startswith(cword_prefix)
                ]
                completions = self.filter_completions(completions)
                completions = self.quote_completions(
                    completions, cword_prequote, last_wordbreak_pos
                )
                return completions
        completions = super(SmartCompletionFinder, self)._get_completions(
            comp_words, cword_prefix, cword_prequote, last_wordbreak_pos
        )
        return completions
