from django.apps import AppConfig


class GestaoContratosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gestao_contratos"

    def ready(self):
        import gestao_contratos.signals  # noqa: F401
