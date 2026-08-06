from __future__ import annotations

from .gui import MacroApp


def main() -> None:
    app = MacroApp()
    app.mainloop()


if __name__ == "__main__":
    main()
