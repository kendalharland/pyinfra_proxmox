class ProxmoxError(Exception):
    def __init__(self, message: str):
        self.message = message

    def __str__(self):
        return f"ProxmoxError: {self.message}"


class InvalidInputError(ProxmoxError):
    def __init__(self, name: str, value: str):
        super().__init__(f"invalid {name}: '{value}'")
