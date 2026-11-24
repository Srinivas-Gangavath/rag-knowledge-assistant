"""Safe application errors for chat and RAG."""


class ChatServiceError(Exception):
    status_code = 400
    public_message = "The question could not be processed."

    def __init__(self, public_message: str | None = None) -> None:
        self.public_message = public_message or self.public_message
        super().__init__(self.public_message)


class EmptyQuestionError(ChatServiceError):
    status_code = 422
    public_message = "A question is required."


class QuestionTooLongError(ChatServiceError):
    status_code = 422
    public_message = "The question exceeds the maximum allowed length."


class ConversationNotFoundError(ChatServiceError):
    status_code = 404
    public_message = "Conversation not found."
