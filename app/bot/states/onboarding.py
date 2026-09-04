from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    """FSM for employee onboarding flow in Telegram."""

    viewing_step = State()
    answering_quiz = State()
    answering_structured_quiz = State()
