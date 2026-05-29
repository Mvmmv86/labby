from dataclasses import dataclass

LABBY_MODULES = {
    "sales": {
        "key": "sales",
        "label": "Vendas",
        "description": "Pre-venda, vendas, pos-venda, suporte e canais de atendimento.",
        "accent": "#00d4aa",
        "accent_bright": "#00eebb",
    },
    "social_media": {
        "key": "social_media",
        "label": "Social Midia",
        "description": "Redes sociais, captura do X, curadoria IA e digest.",
        "accent": "#00a3ff",
        "accent_bright": "#38cfff",
    },
}

DEFAULT_OWNER_MODULES = ("sales", "social_media")


@dataclass(frozen=True)
class ModuleAccess:
    modules: tuple[str, ...]
    default_module: str

    def validate(self) -> None:
        if not self.modules:
            raise ValueError("Pelo menos um modulo precisa estar habilitado")
        invalid = set(self.modules) - set(LABBY_MODULES)
        if invalid:
            raise ValueError(f"Modulos invalidos: {', '.join(sorted(invalid))}")
        if self.default_module not in self.modules:
            raise ValueError("Modulo padrao precisa estar habilitado")


def module_payload(module_key: str) -> dict[str, str]:
    return dict(LABBY_MODULES[module_key])


def modules_payload(module_keys: tuple[str, ...] | list[str]) -> list[dict[str, str]]:
    ordered = [key for key in LABBY_MODULES if key in set(module_keys)]
    return [module_payload(key) for key in ordered]
