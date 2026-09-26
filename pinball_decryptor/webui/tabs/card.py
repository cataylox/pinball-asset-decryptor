"""The web Select card tab (PAD-224): pick the card image (or the card in a
reader) the app works on, and see which tabs work straight from it and
which need it extracted first.

The card itself is still the Extract tab's input (``extract_input_var``
and friends, which the run logic and the other tabs read), so the page
renders the ``extract`` namespace and calls ``extract.*``; this service
only gives the page its rail entry and refreshes the shared state when
the page is shown.
"""

from .base import TabService


class CardTab(TabService):
    ns = "card"
    key = "Select Card"
    label = "Select card"
    group = "Card"
    icon = "sd"

    def on_show(self):
        ext = self.window.service("extract")
        if ext is not None:
            ext.on_show()


TAB = CardTab
