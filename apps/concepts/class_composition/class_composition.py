from typing import Protocol

# Message-sending contract


class MessageSender(Protocol):
    def send(self, message: str) -> bool: ...


# Example third-party client contracts.
# Adjust these to match the actual SDKs.


class TwilioClient(Protocol):
    def send(self, message: str) -> str: ...


class EmailClient(Protocol):
    def deliver(self, message: str) -> bool: ...


###############################################################
# Adapters use structural typing: no MessageSender inheritance.
###############################################################


class TwilioMessageSender:
    def __init__(self, client: TwilioClient):
        self.client = client

    def send(self, message: str) -> bool:
        status = self.client.send(message)
        return status in {"accepted", "queued", "sent", "delivered"}


class EmailMessageSender:
    def __init__(self, client: EmailClient):
        self.client = client

    def send(self, message: str) -> bool:
        return self.client.deliver(message)


###########################################################
# Bridge: business behavior composed with a message sender.
###########################################################


class AlertService:
    def __init__(self, message_sender: MessageSender):
        self.message_sender = message_sender

    def emit(self, alert: str) -> bool:
        return self.message_sender.send(f"ALERT: {alert}")


class WelcomeMessageSender:
    def __init__(self, message_sender: MessageSender):
        self.message_sender = message_sender

    def send(self, prefix: str) -> bool:
        return self.message_sender.send(f"{prefix}, welcome to the platform!")
