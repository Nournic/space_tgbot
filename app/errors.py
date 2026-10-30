"""Игровые исключения. Текст сообщения безопасно показывать пользователю."""

from __future__ import annotations


class GameError(Exception):
    """Ожидаемая ошибка игровой логики; message — готовый текст для игрока."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotRegistered(GameError):
    def __init__(self, message: str = "🛰 Вы ещё не зарегистрированы. Нажмите /register") -> None:
        super().__init__(message)


class ValidationError(GameError):
    pass


class InsufficientFunds(GameError):
    pass


class NotYourButton(GameError):
    def __init__(self) -> None:
        super().__init__("⛔ Эта кнопка не для вас")


class StaleAction(GameError):
    def __init__(self) -> None:
        super().__init__("⏳ Действие устарело, откройте меню снова")
